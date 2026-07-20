"""
Copyright (c) 2015-2016, Uday Agrawal, Adewole Oyalowo, Asaad Lab under MIT License. See full license and associated
project at < https://bitbucket.org/asaadneurolab/pymind/ > .

Last update: 5/23/2016
"""

from abc import ABCMeta, abstractmethod


class ConnectionProtocol(metaclass=ABCMeta):
    """This is an abstract class that contains all the properties and methods
    expected of an additional connection protocol.

    Each connection protocol must implement the methods defined in this class,
    and the rest of the code will make use of the defined attributes.


    Parameters
    ----------
    SaveProtocol: class
        Each connection protocol must utilize a save protocol

    """

    def __init__(self, SaveProtocol):
        # String to specify type of Module
        self.moduleType = None

        # Boolean to indicate whether module successfully connected
        self.isConnected = False

        # Boolean to indicate whether module in the process of connecting
        self.isConnecting = False

        # Initialize a socket via which to connect
        self.socket = None

        # Separate thread for data collection
        self.DataCollectionThread = None

        # SaveProtocol
        self.SaveProtocol = SaveProtocol

    @abstractmethod
    def start(self):
        """
        Turn on data collection thread that targets the connect method
        """
        pass

    @abstractmethod
    def connect(self):
        """
        Connect to hardware
        """
        pass

    @abstractmethod
    def disconnect(self):
        """
        Disconnect from hardware
        """
        pass


if __name__ == "__main__":
    pass
