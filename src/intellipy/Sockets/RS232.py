"""
Copyright (c) 2015-2016, Uday Agrawal, Adewole Oyalowo, Asaad Lab under MIT License. See full license and associated
project at < https://bitbucket.org/asaadneurolab/pymind/ > .

author: uagrawal, 4/21/16
"""

import struct

import serial

import glob

from intellipy.Sockets import Socket


class RS232(Socket.Socket):
    """Methods to engage in RS232 connection with monitor

    Parameters
    ----------
    device: str
        Serial device name

    timeout: float
        Seconds to wait for serial input before giving up on a frame
    """

    def __init__(self, device, timeout=5):
        super().__init__()
        # Create Serial Port
        try:
            self.socket = serial.Serial(
                port=device,
                baudrate=115200,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=timeout,
            )

            # Create CRC16 Table
            self.CRCTable = self.getCRCTable()

            print("Serial Port Opened.")

        except:
            print("Serial Port Not Detected")

    def bind(self):
        """Binds port to given address (not used in serial)"""
        pass

    def set_timeout(self, timeout):
        """Bound how long `receive` waits for serial input.

        Parameters
        ----------
        timeout: float or None
            Seconds to wait, or None to block indefinitely.

        """
        self.timeout = timeout
        if hasattr(self, "socket"):
            self.socket.timeout = timeout

    def send(self, message):
        """Sends the finalized message to the monitor"""
        self.socket.write(self.frameCheckWrite(message))

    def receive(self):
        """Takes in input from serial port and strings into messages
        based on start bit (0xC0) and stop bit (0xC1)

        will stop after reading in one message

        Returns
        -------
        finalMessage: bytearray
            byte message to be passed on to parser

        """

        # initialize message
        message = bytearray()

        # initialize boolean
        messageNotDone = True

        # read in current byte
        currentByte = self.socket.read(1)

        # Loop to read in entire message
        if currentByte == b"\xc0":
            message = message + currentByte

            while messageNotDone:
                messageByte = self.socket.read(1)

                if messageByte != b"\xc1":
                    message = message + messageByte
                else:
                    message = message + messageByte
                    messageNotDone = False

            # Frame check message
            finalMessage = self.frameCheckRead(bytes(message))

        # If not at start bit return nothing
        else:
            finalMessage = b""

        return finalMessage

    def close(self):
        """Closes socket"""

        if hasattr(self, "socket"):
            self.socket.close()
            print("Serial Port Closed.")

    def __del__(self):
        """Deletes socket"""
        self.close()

    # Returns value from uint16 binary
    def get16(self, data):
        """Returns value from uint16 binary

        Parameters
        ----------
        data: uint16 bytes
            value to be unpacked

        Returns
        -------
        unpacked uint16 bytes: int

        """
        return struct.unpack(">H", data)[0]

    # Returns uint16 binary from value
    def set16(self, data):
        """Returns uint16 binary from value

        Parameters
        ----------
        data: uint16 int
            value to be packed

        Returns
        -------
        packed uint16 int: bytearray

        """
        return bytearray(struct.pack(">H", data))

    # create CRC16 table
    def getCRCTable(self):
        """generates table used in CRC16 calculations (as defined in manual)

        Returns
        -------
        table: list
            table of 16 bit numbers

        """

        table = list()

        for i in range(0, 256):
            x = i
            for _ in range(0, 8):
                if x & 1:
                    x = (x >> 1) ^ 0x8408
                else:
                    x = x >> 1

            table.append(x & 0xFFFF)

        return table

    # get CRC16
    def getCRC16(self, message, table):
        """generates CRC16 as defined by manual

        Parameters
        ----------
        message: bytes
            message to be converted

        table: list
            CRCTable

        Returns
        -------

        fcs: bytes
            frame check sequenced message

        returns: fcs - 16 bit crc code
        """
        length = len(message)
        fcs = 0xFFFF

        for i in range(0, length):
            fcs = (fcs >> 8) ^ table[(fcs ^ message[i]) & 0xFF]

        # One's Complement
        fcs = ~fcs & 0xFFFF

        # Byte Swap
        fcs = struct.pack("<H", fcs)

        return fcs

    # write transparency check
    def writeTransparencyCheck(self, message):
        """performs transparency check on written messages as defined by manual

        Parameters
        ----------
        message: bytes
            message to be converted

        Returns
        -------

        message: bytes
            bytes to be sent to monitor

        """
        # iterate through each byte for start, stop, esc bytes
        for i in range(1, len(message) - 1):
            if message[i] == 0xC0 or message[i] == 0xC1 or message[i] == 0x7D:
                replace_byte = message[i] ^ 0x20
                message[i] = 0x7D
                message.insert(i + 1, replace_byte)

        return message

    # read transparency check
    def readTransparencyCheck(self, message):
        """performs transparency check on written messages as defined by manual

        Parameters
        ----------
        message: bytes
            message to be converted

        Returns
        -------

        message: bytes
            bytes ready to be read

        """

        if type(message) != bytearray:
            message = bytearray(message)

        # store (index, bin) in these lists
        indices = []

        # iterate through message and store indices of 0xc1,0xc0,0x7d
        for i in range(0, len(message)):
            if message[i] == 0x7D:
                if message[i + 1] == 0xC0 ^ 0x20:
                    indices.append((i, 192))  # 0xc0 = 192
                elif message[i + 1] == 0xC1 ^ 0x20:
                    indices.append((i, 193))  # 0xc1 = 193
                elif message[i + 1] == 0x7D ^ 0x20:
                    indices.append((i, 125))  # 0x7d = 125

        # Sort indices
        sortedIndices = sorted(indices, reverse=True)

        # Iterate through list and change message
        for value in sortedIndices:
            if value[1] == 192:
                message[value[0] : value[0] + 2] = b"\xc0"
            elif value[1] == 193:
                message[value[0] : value[0] + 2] = b"\xc1"
            elif value[1] == 125:
                message[value[0] : value[0] + 2] = b"\x7d"

        return bytes(message)

    # Adds header, fcs, transparency check to messages
    def frameCheckWrite(self, message):
        """Takes message and adds beginning of frame, header, fcs, end of frame,
        as well as performs transparency check

        Frame = (BOF,Hdr,Hdr_len,message,FCS,EOF)

        Parameters
        ----------
        message: bytes
            message to be converted

        Returns
        -------

        finalMessage: bytes
            final message to be sent to monitor

        """

        BOF = bytearray(b"\xc0")

        Hdr = bytearray(b"\x11\x01")

        Hdr_len = self.set16(len(message))

        FCS = bytearray(self.getCRC16(Hdr + Hdr_len + message, self.CRCTable))

        EOF = bytearray(b"\xc1")

        finalMessage = self.writeTransparencyCheck(
            BOF + Hdr + Hdr_len + message + FCS + EOF
        )
        return finalMessage

    # Reads in and interprets framing of messages
    def frameCheckRead(self, message):
        """Reads in messages and strips BOF, Hdr, FCS, EOF,
        so it can be read by IntellivueData.readData

        Also checks FCS to ensure proper format

        Parameters
        ----------
        message: bytes
            message to be converted

        Returns
        -------
        finalMessage: bytes
            final message to be read

        """

        # Check for start bit and correct protocol id
        if message[0:3] == b"\xc0\x11\x01":
            # Transparency Check (not including start, stop)
            message = self.readTransparencyCheck(message[1:-1])

            # Length, CRC calculations
            length = self.get16(message[2:4])
            givenCRC = message[4 + length : 6 + length]
            validatedCRC = self.getCRC16(message[: 4 + length], self.CRCTable)

            # Check that CRC's match up, otherwise ignore message
            if givenCRC == validatedCRC:
                finalMessage = message[4 : 4 + length]
            # If they are not the same, output CRC mismatch
            else:
                finalMessage = b""

        else:
            print("Incorrect framing...")

        return finalMessage


if __name__ == "__main__":
    pass
