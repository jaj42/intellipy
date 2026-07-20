"""
Copyright (c) 2015-2016, Uday Agrawal, Adewole Oyalowo, Asaad Lab under MIT License. See full license and associated
project at < https://bitbucket.org/asaadneurolab/pymind/ > .

Author: uagrawal, aoyalowo
Last update: 5/23/2016
"""

import datetime
import json
import os.path

import numpy as np


class SaveAsQueue(object):
    """SaveAsQueue is an example of a SaveProtocol required to save the data recorded via pyMIND.

    Each ConnectionProtocol must create an instance of a SaveProtocol that specifies how the data is saved.

    Parameters
    ----------
    numQueue: Queue
        Queue which receives Numerics

    waveQueue: Queue
        Queue which receives Waves

    alarmQueue: Queue
        Queue which receives Alarms
    """

    def __init__(self, numQueue=None, waveQueue=None, alarmQueue=None):
        self.numq = numQueue
        self.waveq = waveQueue
        self.alarmq = alarmQueue

        # Initialize variables to store time values
        self._initialTimeDateTime = datetime.datetime.now()

        # Set buffer size
        self._fileSizeOnRAM = 128  # file size in seconds of data stored on RAM

        # Stores the numpy arrays of data
        self._VitalsWaveData = {}
        self._VitalsNumericsData = {}

        # Additional attributes of data stream
        self._VitalsWaveInfo = {}
        self._VitalsNumericsInfo = {}

    # Stores initial time, which all following times are based off
    def saveVitalsInitialTime(self, decodedInitialTime, relativeDecodedInitialTime):
        """If new directory name specified, re-initialize appropriate variables

        Parameters
        ----------
        decodedInitialTime: dict
            Initial timestamp provided by monitor

        relativeDecodedInitialTime: int
            Relative time from initial timestamp provided by monitor

        """

        self._vitalsInitialTime = "{0}/{1}/{2}{3}, {4}:{5}:{6}".format(
            decodedInitialTime["month"],
            decodedInitialTime["day"],
            decodedInitialTime["century"],
            decodedInitialTime["year"],
            decodedInitialTime["hour"],
            decodedInitialTime["minute"],
            decodedInitialTime["second"],
        )
        self._relativeVitalsInitialTime = relativeDecodedInitialTime
        self._vitalsInitialTimeDateTime = datetime.datetime(
            decodedInitialTime["year"],
            decodedInitialTime["month"],
            decodedInitialTime["day"],
            decodedInitialTime["hour"],
            decodedInitialTime["minute"],
            decodedInitialTime["second"],
        )

    # Initialize the extracted properties from Vitals Numeric
    def initializeVitalsNumericsData(self, label, Units):
        """Initializes vitals numeric numpy arrays

        Parameters
        ----------
        label: str
            Vitals numeric type

        Units: str
            Vitals numeric units

        """

        # Check to make sure label isn't already in self.VitalsNumericsInfo
        if label not in self._VitalsNumericsInfo:
            # Initialize to store attributes of data type
            self._VitalsNumericsInfo[label] = {}

            # Inititalize Index
            self._VitalsNumericsInfo[label]["SamplingFreq"] = 1 / 1.024
            self._VitalsNumericsInfo[label]["Units"] = str(Units)

            # Initialize numpy array
            self._VitalsNumericsData[label] = np.zeros(
                (
                    2,
                    int(
                        self._VitalsNumericsInfo[label]["SamplingFreq"]
                        * self._fileSizeOnRAM
                    ),
                ),
                dtype="float32",
            )

            self._VitalsNumericsData[label].fill(np.nan)

    # Initialize the extracted properties from Vitals Wave
    def initializeVitalsWaveData(
        self, label, fs, ValueConversion, Units, Handle, displayName
    ):
        """Initializes vitals wave numpy arrays

        Parameters
        ----------
        label: str
            Vitals wave type

        fs: int
            Vitals wave sampling frequency

        ValueConversion: tuple
            Linear conversion values (ie y = mx + b)

        Units: str
            Vitals wave units

        Handle: int
            Vitals wave identifier handle

        displayName: str
            Standardized string label of vitals wave

        """
        # If this label isn't in self.VitalsWaveInfo, then initialize values for it
        if label not in self._VitalsWaveInfo:
            # Stores basic attributes of each data type
            self._VitalsWaveInfo[label] = {}

            # Initialize numpy array for timestamps and data =
            self._VitalsWaveData[label] = np.zeros(
                (2, fs * self._fileSizeOnRAM), dtype="float32"
            )

            # Initialize linear conversion values (ie y = mx + b)
            self._VitalsWaveInfo[label]["ValueConversion"] = ValueConversion

            # Inititialize Handle (to help uniquely identify scada)
            self._VitalsWaveInfo[label]["Handle"] = Handle

            # Name to be displayed in visualization for readability
            self._VitalsWaveInfo[label]["displayName"] = displayName

            self._VitalsWaveInfo[label]["Units"] = str(Units)

            self._VitalsWaveInfo[label]["SamplingFreq"] = fs

    # Save the wave data
    def saveVitalsWaveData(self, label, temp_array, relativeTime):
        """Saves data into numpy arrays with timestamps

        Parameters
        ----------
        label: str
            Vitals wave type

        temp_array: list
            Vitals data

        relativeTime: int
            Vitals data timestamp

        """
        if self.waveq is None:
            return

        temp_times = np.linspace(
            (relativeTime - self._relativeVitalsInitialTime) / 8000,
            (relativeTime - self._relativeVitalsInitialTime) / 8000
            + temp_array.size / self._VitalsWaveInfo[label]["SamplingFreq"],
            temp_array.size,
            endpoint=False,
        )

        tdy = (
            temp_array * self._VitalsWaveInfo[label]["ValueConversion"][0]
            + self._VitalsWaveInfo[label]["ValueConversion"][1]
        )
        td = {"label": label, "time": temp_times.tolist(), "wave": tdy.tolist()}
        self.waveq.put(td)

    # Save the numeric data
    def saveVitalsNumericsData(self, label, temp_value, relativeTime):
        """Saves data into numpy arrays with timestamps

        Parameters
        ----------
        label: str
            Vitals numeric type

        temo_value: int
            Vitals numeric data

        relativeTime: int
            Vitals data timestamp

        """
        if self.numq is None:
            return

        # temporary time values
        temp_time = (relativeTime - self._relativeVitalsInitialTime) / 8000

        # If its a string, then don't store it
        if type(temp_value) != str:
            data = {"label": label, "time": temp_time, "value": temp_value}
            # print(data)
            self.numq.put(data)

    # Save the alarm data
    def saveVitalsAlarmsData(
        self, relativeTime, alarmEntry, code, source, alarmType, state, alarmString
    ):
        """Saves data into numpy arrays with timestamps and writes to file

        Parameters
        ----------
        relativeTime: int
            alarm timestamp

        alarmEntry: str
            alarm identifier

        code: str
            alarm code

        source: str
            alarm source

        alarmType: str
            alarm type

        state: str
            alarm state

        alarmString: str
            alarm info
        """
        if self.alarmq is None:
            return

        # Time
        currentTime = self._initialTimeDateTime + datetime.timedelta(
            seconds=((relativeTime - self._relativeVitalsInitialTime) / 8000)
        )
        currentTime = str(currentTime.time())

        # Initialize dictionary to store values in
        self.AlarmsDict = {}
        self.AlarmsDict[currentTime] = {}
        self.AlarmsDict[currentTime][alarmEntry] = {}

        # Store values
        self.AlarmsDict[currentTime][alarmEntry]["code"] = code
        self.AlarmsDict[currentTime][alarmEntry]["source"] = source
        self.AlarmsDict[currentTime][alarmEntry]["alarmType"] = alarmType
        self.AlarmsDict[currentTime][alarmEntry]["code"] = code
        self.AlarmsDict[currentTime][alarmEntry]["state"] = state
        self.AlarmsDict[currentTime][alarmEntry]["alarmString"] = alarmString

        self.alarmq.put(self.AlarmsDict)


if __name__ == "__main__":
    pass
