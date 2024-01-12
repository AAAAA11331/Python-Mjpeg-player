import argparse
import socket
import threading
from random import randint
from time import time

import Complete

# Setup code.
SETUP = 0

# Play code.
PLAY = 1

# Pause code.
PAUSE = 2

# Teardown code.
TEARDOWN = 3

# The value for needing to be setup state.
INIT = 0

# The value for the ready to play state (can also think of this as paused).
READY = 1

# The value for the playing state.
PLAYING = 2

# Value to return for an okay.
OK_200 = 0

# Value to return for a 404 error.
FILE_NOT_FOUND_404 = 1

# Value to return for a 500 error.
CONNECTION_ERROR_500 = 2


class Server:
    """
    Contains all logic for running the server.
    """

    def __init__(self, server_port: int) -> None:
        """
        Set up the server
        :param server_port: The port for the server to run on..
        """
        # Set up the socket.
        rtsp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        rtsp_socket.bind(('', server_port))
        rtsp_socket.listen(5)
        # Setup unique RTP values for this run.
        self.version = 2
        self.padding = 0
        self.cc = 0
        self.marker = 0
        self.payload_type = 26
        self.ssrc = 0
        # Receive client info (address, port) through RTSP/TCP session.
        client_info = {"rtsp_socket": rtsp_socket.accept()}
        self.client_info = client_info
        self.state = INIT
        self.run()

    def run(self) -> None:
        """
        Run the server.
        :return: Nothing.
        """
        threading.Thread(target=self.receive_rtsp_request).start()

    def receive_rtsp_request(self) -> None:
        """
        Receive RTSP request from the client.
        :return: Nothing.
        """
        connection_socket = self.client_info["rtsp_socket"][0]
        while True:
            try:
                data = connection_socket.recv(256)
            except:
                # For simplicity, losing connection shuts down the server so both can easily be started together.
                break
            if not data:
                continue
            print(f"Data received: {data.decode('utf-8')}")
            request = data.decode("utf-8").split("|")
            # Get the RTSP sequence number.
            sequence_number = request[0]
            # Get the request type.
            request_type = int(request[1])
            # Process SETUP request.
            if request_type == SETUP:
                if self.state == INIT:
                    # Update state.
                    try:
                        self.client_info["video_stream"] = {"File": open(request[2], "rb"), "Number": 0}
                        self.state = READY
                    except IOError:
                        self.reply_rtsp(FILE_NOT_FOUND_404, sequence_number)
                    # Generate a randomized RTSP session ID.
                    self.client_info["session"] = randint(100000, 999999)
                    # Send RTSP reply
                    self.reply_rtsp(OK_200, sequence_number)
                    # Get the RTP/UDP port from the last line.
                    self.client_info["rtp_port"] = request[3]
            # Process PLAY request.
            elif request_type == PLAY:
                if self.state == READY:
                    self.state = PLAYING
                    # Create a new socket for RTP/UDP.
                    self.client_info["rtp_socket"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    self.reply_rtsp(OK_200, sequence_number)
                    # Create a new thread and start sending RTP packets.
                    self.client_info["event"] = threading.Event()
                    self.client_info["worker"] = threading.Thread(target=self.send_rtp)
                    self.client_info["worker"].start()
            # Process PAUSE request.
            elif request_type == PAUSE:
                if self.state == PLAYING:
                    self.state = READY
                    self.client_info["event"].set()
                    self.reply_rtsp(OK_200, sequence_number)
            # Process TEARDOWN request.
            elif request_type == TEARDOWN:
                self.client_info["event"].set()
                self.reply_rtsp(OK_200, sequence_number)
                self.client_info["rtp_socket"].close()
                # For simplicity, shut down the server so both can easily be started together.
                break

    def send_rtp(self) -> None:
        """
        Send RTP packets over UDP.
        :return: Nothing.
        """
        while True:
            self.client_info["event"].wait(0.05)
            # Stop sending if request is PAUSE or TEARDOWN
            if self.client_info["event"].is_set():
                break
            # Get the frame length from the first 5 bits.
            data = self.client_info["video_stream"]["File"].read(5)
            if data:
                frame_length = int(data)
                # Read the current frame.
                data = self.client_info["video_stream"]["File"].read(frame_length)
                self.client_info["video_stream"]["Number"] += 1
            if data:
                sequence_number = self.client_info["video_stream"]["Number"]
                try:
                    address = self.client_info["rtsp_socket"][1][0]
                    port = int(self.client_info["rtp_port"])
                    # Define the header.
                    header = bytearray(12)
                    Complete.rtp_header(header, self.version, self.padding, 0, self.cc, self.marker, self.payload_type, sequence_number, int(time()), self.ssrc)
                    self.client_info["rtp_socket"].sendto(header + data, (address, port))
                    print(f"RTP Sequence Number Sent: {sequence_number}")
                except:
                    print("Connection Error")
    def rtp_header(header: bytearray, version: int, padding: int, extension: int, cc: int, marker: int, payload_type: int, sequence_number: int, timestamp: int, ssrc: int) -> None:
        header[0] = (version << 6) | (padding << 5) | (extension << 4) | cc
        header[1] = (marker << 7) | payload_type
        header[2] = (sequence_number >> 8) & 0xFF
        header[3] = sequence_number & 0xFF
        header[4] = (timestamp >> 24) & 0xFF
        header[5] = (timestamp >> 16) & 0xFF
        header[6] = (timestamp >> 8) & 0xFF
        header[7] = timestamp & 0xFF
        header[8] = (ssrc >> 24) & 0xFF
        header[9] = (ssrc >> 16) & 0xFF
        header[10] = (ssrc >> 8) & 0xFF
        header[11] = ssrc & 0xFF
    """
    Encode the RTP header fields for the server to send to the client.
    :param header: The header byte array of 12 bytes to fill.
    :param version: (2 bits) Indicates the version of the protocol.
    :param padding: (1 bit) Used to indicate if there are extra padding bytes at the end of the RTP packet.
    Padding may be used to fill up a block of certain size, for example as required by an encryption algorithm.
    The last byte of the padding contains the number of padding bytes that were added (including itself).
    :param extension: (1 bit) Indicates presence of an extension header between the header and payload data.
    The extension header is application or profile specific.
    :param cc: (4 bits) Contains the number of CSRC identifiers that follow the SSRC.
    :param marker: (1 bit) Signaling used at the application level in a profile-specific manner.
    If it is set, it means that the current data has some special relevance for the application.
    :param payload_type: (7 bits) Indicates the format of the payload and thus determines its interpretation by the
    application. Values are profile specific and may be dynamically assigned.
    :param sequence_number: (16 bits) The sequence number is incremented for each RTP data packet sent and is to be used
    by the receiver to detect packet loss and to accommodate out-of-order delivery.
    :param timestamp: The timestamp for use in certain header fields.
    :param ssrc: (32 bits) Synchronization source identifier uniquely identifies the source of a stream.
    The synchronization sources within the same RTP session will be unique.
    :return: Nothing.
    """
    



    def reply_rtsp(self, code: int, seq: str) -> None:
        """
        Send RTSP reply to the client.
        :param code: The code to send.
        :param seq: The sequence number.
        :return: Nothing.
        """
        if code == OK_200:
            reply = f"200|{seq}|{self.client_info['session']}"
        elif code == FILE_NOT_FOUND_404:
            reply = "404"
            print("404 FILE NOT FOUND")
        else:
            reply = "500"
            print("500 CONNECTION ERROR")
        self.client_info["rtsp_socket"][0].send(reply.encode())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, description="Server")
    parser.add_argument("server_port", nargs='?', type=int, help="The port number to run on.", default=7777)
    a = vars(parser.parse_args())
    Server(a["server_port"])