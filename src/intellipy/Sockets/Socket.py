"""
Copyright (c) 2015-2016, Uday Agrawal, Adewole Oyalowo, Asaad Lab under MIT License. See full license and associated
project at < https://bitbucket.org/asaadneurolab/pymind/ > .

author: uagrawal, 4/21/16
"""

from abc import ABCMeta, abstractmethod


class Socket(metaclass=ABCMeta):
    """This is an abstract class that contains all the properties and methods
    expected of an additional socket.

    Each socket must implement the methods defined in this class, and the rest
    of the code will make use of the defined attributes.
    """

    @abstractmethod
    def bind(self):
        """Binds port to given address"""
        pass

    @abstractmethod
    def send(self):
        """Sends message"""
        pass

    @abstractmethod
    def receive(self):
        """Receives messages"""
        pass

    @abstractmethod
    def close(self):
        """Closes socket"""
        pass

    @abstractmethod
    def __del__(self):
        """Terminates socket in case of faulty close"""


if __name__ == "__main__":
    pass
