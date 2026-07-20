"""
Copyright (c) 2015-2016, Uday Agrawal, Adewole Oyalowo, Asaad Lab under MIT License. See full license and associated
project at < https://bitbucket.org/asaadneurolab/pymind/ > .

author: uagrawal, 4/21/16
"""

import socket

from intellipy.Sockets import Socket


class UDP(Socket.Socket):
    """Methods to engage in UDP connection

    Parameters
    ----------
    portAddress: str
        Data port address

    portNumber: int
        Data port number

    timeout: float or None
        Seconds to wait in `receive` before raising `socket.timeout`. None
        (the default) blocks forever, as the original driver did.

    """

    def __init__(self, portAddress="0.0.0.0", portNumber=24005, timeout=None):
        super().__init__()
        # Create socket
        # AF_INET = Address and protocol family (internet)
        # SOCK_DGRAM = Socket type (UDP)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Initialize portAddress (in this case serial port location)
        self.portAddress = portAddress

        # Port Number (specified in manual p29)
        self.portNumber = portNumber

        # Buffer Size (specified in manual p29)
        self.buffer_size = 2048

        self.set_timeout(timeout)

    def set_timeout(self, timeout):
        """Bound how long `receive` blocks.

        Parameters
        ----------
        timeout: float or None
            Seconds to wait for a datagram, or None to block indefinitely.

        """
        self.timeout = timeout
        self.socket.settimeout(timeout)

    def bind(self):
        """Binds port to given address"""
        print("Connecting to UDP Socket...")
        self.socket.bind((self.portAddress, self.portNumber))

    def send(self, message):
        """Sends message

        Parameters
        ----------
        message: bytes
            message to send

        port: int
            port to send message

        IP: string
            IP address to send to

        """
        self.socket.sendto(message, (self.portAddress, self.portNumber))

    def receive(self):
        """Receives message

        Returns
        -------
        udp_data: bytes
            received message

        """

        udp_data = ""
        while udp_data == "":
            udp_data, address = self.socket.recvfrom(self.buffer_size)
        return udp_data

    def close(self):
        """closes socket"""
        self.socket.close()
        print("UDP Socket Closed.")

    def __del__(self):
        """Terminates socket in case of faulty close"""
        self.close()


if __name__ == "__main__":
    pass
