import argparse
import os
import socket
import threading
from tkinter import *
from tkinter import messagebox

from PIL import Image, ImageTk

import Complete
from Server import SETUP, PLAY, PAUSE, TEARDOWN, INIT, READY, PLAYING

# Client frame cache prefix.
CACHE_FILE_NAME = "cache-"

# Client frame cache extension.
CACHE_FILE_EXT = ".jpg"


def cleanup() -> None:
    """
    Delete the cached images from video.
    :return: Nothing
    """
    while True:
        was_file = False
        files = os.listdir(os.getcwd())
        for file in files:
            if os.path.isdir(file):
                continue
            elif file.__contains__(CACHE_FILE_EXT):
                was_file = True
                try:
                    os.remove(file)
                except:
                    pass
        if not was_file:
            return


class Client:
    """
    Contains all logic for running the client.
    """

    def __init__(self, server_address: str, server_port: str, rtp_port: str, video_file: str) -> None:
        """
        Initiation of the client.
        :param server_address: The server address to connect to.
        :param server_port: The server port to connect on.
        :param rtp_port: The port to send RTP data over.
        :param video_file: The video file to request to play.
        """
        cleanup()
        self.server_address = server_address
        self.server_port = int(server_port)
        self.rtp_port = int(rtp_port)
        self.video_file = video_file
        self.sequence_number = 0
        self.session_id = 0
        self.request_sent = -1
        self.ui = Tk()
        self.ui.title = "Client"
        self.ui.protocol("WM_DELETE_WINDOW", self.handler)
        self.play_event = None
        self.rtp_socket = None
        self.data = None
        # Create button.
        self.start = Button(self.ui, width=60, padx=3, pady=3)
        self.start["text"] = "Pause"
        self.start["command"] = self.button_logic
        self.start.grid(row=1, column=0, padx=2, pady=2)
        # Create a label to display the movie.
        self.label = Label(self.ui, height=19)
        self.label.grid(row=0, column=0, columnspan=4, sticky=W + E + N + S, padx=5, pady=5)
        self.state = INIT
        # Connect to the Server. Start a new RTSP/TCP session.
        self.rtsp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.rtsp_socket.connect((self.server_address, self.server_port))
        except:
            messagebox.showwarning("Connection Failed", f"Connection to {self.server_address}:{self.server_port} failed.")
        # Call to set up.
        self.last_sequence_number = -1
        threading.Thread(target=self.receive_rtsp_reply, daemon=True).start()
        self.send_rtsp_request(SETUP)
        self.ui.mainloop()

    def button_logic(self) -> None:
        """
        Handle the logic for the button.
        :return: Nothing.
        """
        # If currently playing, clicking will pause.
        if self.state == PLAYING:
            self.send_rtsp_request(PAUSE)
            self.start["text"] = "Play"
        # Otherwise if ready to play (paused), clicking will play.
        elif self.state == READY:
            self.play()

    def play(self) -> None:
        """
        Play the video.
        :return: Nothing.
        """
        threading.Thread(target=self.listen_rtp, daemon=True).start()
        self.play_event = threading.Event()
        self.play_event.clear()
        self.send_rtsp_request(PLAY)
        self.start["text"] = "Pause"

    def listen_rtp(self) -> None:
        """
        Listen for RTP packets.
        :return: Nothing.
        """
        while True:
            try:
                if self.request_sent == TEARDOWN:
                    break
                data = self.rtp_socket.recv(20480)
                if data:
                    header = bytearray(data[:12])
                    data = data[12:]
                    # Get the sequence (frame) number.
                    current_sequence_number = int(header[2] << 8 | header[3])
                    # Discard late packets.
                    if current_sequence_number > self.last_sequence_number:
                        self.last_sequence_number = current_sequence_number
                        print(f"RTP Sequence Number Received: {self.last_sequence_number}")
                        # Update the image file as video frame in the GUI.
                        cache_name = f"{CACHE_FILE_NAME}{self.session_id}{CACHE_FILE_EXT}"
                        file = open(cache_name, "wb")
                        file.write(data)
                        file.close()
                        photo = ImageTk.PhotoImage(Image.open(cache_name))
                        self.label.configure(image=photo, height=288)
                        self.label.image = photo
            except:
                # Stop listening upon requesting PAUSE or TEARDOWN.
                if self.play_event.is_set():
                    break

    def send_rtsp_request(self, request_code: int) -> None:
        """
        Send RTSP request to the server.
        :param request_code: The request code.
        :return: Nothing.
        """
        # Ensure the request is valid.
        if not ((request_code == SETUP and self.state == INIT) or
                (request_code == PLAY and self.state == READY) or
                (request_code == PAUSE and self.state == PLAYING) or
                request_code == TEARDOWN):
            return
        # Update RTSP sequence number.
        self.sequence_number += 1
        Complete.rtsp_payload(self, self.sequence_number, request_code, self.video_file, self.rtp_port)
        # Set the last sent code.
        self.request_sent = request_code
        # Send the RTSP request using rtspSocket.
        self.rtsp_socket.send(self.data.encode())
        print(f"Data sent: {self.data}")

    
    def rtsp_payload(client: Client, sequence_number: int, request: int, video_file: str, rtp_port: int) -> None:
        client.data = f"{sequence_number}|{request}|{video_file}|{rtp_port}" if request==0 else f"{sequence_number}|{request}"
    """
    Construct the RTSP payload for the client to send to the server.
    :param client: The client this packet is from.
    :param sequence_number: The sequence number of the packet.
    :param request: The request type being either 0 for SETUP, 1 for PLAY, 2 for PAUSE, or 3 for TEARDOWN.
    :param video_file: The name of the video file.
    :param rtp_port: The RTP port to stream over.
    :return: Nothing.
    """
        


    def receive_rtsp_reply(self) -> None:
        """
        Receive RTSP reply from the server.
        :return: Nothing.
        """
        while True:
            reply = self.rtsp_socket.recv(1024)
            if reply:
                # Parse the RTSP reply from the server.
                reply = str(reply.decode("utf-8")).split("|")
                sequence_number = int(reply[1])
                # Process only if the server reply's sequence number is the same as the request's.
                if sequence_number == self.sequence_number:
                    session = int(reply[2])
                    # New RTSP session ID.
                    if self.session_id == 0:
                        self.session_id = session
                    # Process only if the session ID is the same.
                    if self.session_id == session:
                        if int(reply[0]) == 200:
                            if self.request_sent == SETUP:
                                # Update RTSP state..
                                self.state = READY
                                # Create a new datagram socket to receive RTP packets from the server.
                                self.rtp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                                # Set the timeout value of the socket to 0.5 seconds.
                                self.rtp_socket.settimeout(0.5)
                                try:
                                    # Bind the socket to the address using the RTP port given by the client user.
                                    self.rtp_socket.bind(("", self.rtp_port))
                                except:
                                    messagebox.showwarning("Unable to Bind", f"Unable to bind to port {self.rtp_port}")
                                self.play()
                            elif self.request_sent == PLAY:
                                self.state = PLAYING
                            elif self.request_sent == PAUSE:
                                self.state = READY
                                self.play_event.set()
                            elif self.request_sent == TEARDOWN:
                                self.state = READY
                                self.play_event.set()
                                self.rtsp_socket.shutdown(socket.SHUT_RDWR)
                                self.rtsp_socket.close()
                                break

    def handler(self) -> None:
        """
        Handler on explicitly closing the GUI window.
        :return:
        """
        self.send_rtsp_request(TEARDOWN)
        cleanup()
        self.ui.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, description="Client")
    parser.add_argument("server_address", nargs='?', type=str, help="The server's address.", default="127.0.0.1")
    parser.add_argument("server_port", nargs='?', type=int, help="The server's port number.", default=7777)
    parser.add_argument("rtp_port", nargs='?', type=int, help="The port number to run on.", default=7778)
    parser.add_argument("video_file", nargs='?', type=str, help="The video file to play.", default="movie.Mjpeg")
    a = vars(parser.parse_args())
    Client(a["server_address"], a["server_port"], a["rtp_port"], a["video_file"])
