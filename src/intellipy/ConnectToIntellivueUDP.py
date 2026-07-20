"""
Copyright (c) 2015-2016, Uday Agrawal, Adewole Oyalowo, Asaad Lab under MIT License. See full license and associated
project at < https://bitbucket.org/asaadneurolab/pymind/ > .

Author: uagrawal, aoyalowo
Last update: 5/23/2016
"""

import threading  # separate data collection thread
import numpy as np
import datetime

from intellipy import ConnectionProtocol  # abstract base class
from intellipy.IntellivueDataFiles.IntellivueData import IntellivueData  # data parsing

from intellipy.Sockets.UDP import UDP  # socket type


# FIXME: This class/file is most likely deprecated. Unresolved references to GUI. Should not need to rely on GUI to connect.
# TODO: Attempted to fix class by removing self.GUI and replacing with self. Possible I introduced this error in the first place.


class ConnectToIntellivueUDP(ConnectionProtocol.ConnectionProtocol):
    """
    This class utilizes the data structures defined in IntellivueData and
    the functions in openUDP to communicate with the monitor.

    Parameters
    ----------
    selectedDataTypes: list
        Desired wave data streams to be collected

    SaveProtocol: class
        Each connection protocol must utilize a save protocol
    """

    def __init__(self, selectedDataTypes, SaveProtocol):
        super().__init__(SaveProtocol)

        # String to specify type of Module
        self.moduleType = "Vitals"

        # Boolean to indicate whether module successfully connected
        self.isConnected = False

        # Initialize a socket via which to connect
        self.socket = UDP()

        # Separate thread for data collection
        self.DataCollectionThread = threading.Thread(target=self.connect)
        self.DataCollectionThread.daemon = True

        # Initialize IntellivueData
        self.Intellivue = IntellivueData()

        # Initialize variables to keep track of time, and values to collect
        self.dataCollectionTime = 60 * 60 * 72  # in seconds (ie 3 days)
        self.dataCollection = {"RelativeTime": self.dataCollectionTime * 8000}
        self.KeepAliveTime = 0
        self.messageTimes = []
        self.desiredWaveParams = {"TextIdLabel": selectedDataTypes}
        self.initialTime = 0
        self.relativeInitialTime = 0

        #  Initialize Messages
        self.AssociationRequest = self.Intellivue.writeData("AssociationRequest")
        self.AssociationAbort = self.Intellivue.writeData("AssociationAbort")
        self.ConnectIndication = {}
        self.AssociationResponse = ""
        self.MDSCreateEvent = {}
        self.MDSParameters = {}
        self.MDSCreateEventResult = ""
        self.MDSSetPriorityListWave = self.Intellivue.writeData(
            "MDSSetPriorityListWAVE", self.desiredWaveParams
        )
        self.MDSSetPriorityListNumeric = ""
        self.MDSSetPriorityListResultWave = {}
        self.MDSSetPriorityListResultNumeric = {}
        self.MDSGetPriorityList = self.Intellivue.writeData("MDSGetPriorityList")
        self.MDSGetPriorityListResult = {}
        self.ReleaseRequest = self.Intellivue.writeData("ReleaseRequest")
        self.MDSExtendedPollActionNumeric = self.Intellivue.writeData(
            "MDSExtendedPollActionNUMERIC", self.dataCollection
        )
        self.MDSExtendedPollActionWave = self.Intellivue.writeData(
            "MDSExtendedPollActionWAVE", self.dataCollection
        )
        self.MDSExtendedPollActionAlarm = self.Intellivue.writeData(
            "MDSExtendedPollActionALARM", self.dataCollection
        )
        self.KeepAliveMessage = self.Intellivue.writeData("MDSSinglePollAction")

    def start(self):
        """Initiates connection with vitals monitor"""
        if hasattr(self.socket, "socket"):
            self.DataCollectionThread.start()

    def connect(self):
        """Connect to vitals montior via UDP"""
        connected = self.initiateAssociation()

        if connected:
            self.isConnected = True
            self.setPriorityLists()
            self.pullData()
            self.endConnection()
            self.isConnected = False
        else:
            self.isConnected = False
            # Close UDP Port
            self.socket.close()

    def disconnect(self):
        """Cleanly abort connection

        Returns
        -------
        True (indicates disconnect successful)
        """
        self.endConnection()
        return True

    # Establish an Association with the monitor
    def initiateAssociation(self):
        """Initiate handshake with monitor.

        Reads in ConnectIndicationEvent, sends AssociationRequest,
        reads in AssociationResponse and MDSCreateEvent,
        sends MDSCreateEventResult

        Returns
        -------
        True (indicates association successful)
        """

        # Looks out at all IPs and ports 24005 for monitors
        self.socket.bind()

        # Reads in Connect Indication Event and sends Association Request
        no_connection = True
        while no_connection:
            message = self.socket.receive()
            message_type = self.Intellivue.getMessageType(message)
            print("Received " + message_type + ".")

            if message_type == "ConnectIndicationEvent":
                self.ConnectIndication, portNumber, portAddress = (
                    self.Intellivue.readData(message)
                )
                self.socket.portAddress = portAddress
                self.socket.portNumber = portNumber
                self.socket.send(self.AssociationRequest)
                print("Sent Association Request...")
                no_connection = False
            elif message_type == "ReleaseRequest":
                print("Connection Aborted.")
                no_connection = False
                return False
            else:
                print("Will try looking for ConnectIndicationEvent again...")

        # Reads in Association Response and MDS Create Event and sends
        # MDS Create Event Result
        no_association = True
        while no_association:
            message1 = self.socket.receive()
            message2 = self.socket.receive()
            message_type1 = self.Intellivue.getMessageType(message1)
            message_type2 = self.Intellivue.getMessageType(message2)

            print("Received " + message_type1 + ".")
            print("Received " + message_type2 + ".")

            if (
                message_type1 == "AssociationResponse"
                and message_type2 == "MDSCreateEvent"
            ):
                self.AssociationResponse = self.Intellivue.readData(message1)
                self.KeepAliveTime = (
                    self.AssociationResponse["AssocRespUserData"]["MDSEUserInfoStd"][
                        "supported_aprofiles"
                    ]["AttributeList"]["AVAType"]["NOM_POLL_PROFILE_SUPPORT"][
                        "AttributeValue"
                    ]["PollProfileSupport"]["min_poll_period"]["RelativeTime"]
                    / 8000
                )
                self.MDSCreateEvent, self.MDSParameters = self.Intellivue.readData(
                    message2
                )

                # Store the absolute time marker that everything else will reference
                self.initialTime = self.MDSCreateEvent["MDSCreateInfo"][
                    "MDSAttributeList"
                ]["AttributeList"]["AVAType"]["NOM_ATTR_TIME_ABS"]["AttributeValue"][
                    "AbsoluteTime"
                ]
                self.relativeInitialTime = self.MDSCreateEvent["MDSCreateInfo"][
                    "MDSAttributeList"
                ]["AttributeList"]["AVAType"]["NOM_ATTR_TIME_REL"]["AttributeValue"][
                    "RelativeTime"
                ]

                # Save this in SaveProtocol
                self.SaveProtocol.saveVitalsInitialTime(
                    self.initialTime, self.relativeInitialTime
                )

                # Send MDS Create Event Result
                self.MDSCreateEventResult = self.Intellivue.writeData(
                    "MDSCreateEventResult", self.MDSParameters
                )
                self.socket.send(self.MDSCreateEventResult)

                print("Sent MDS Create Event Result...")
                no_association = False

            else:
                print("Will try sending Association Request again...")
                self.socket.send(self.AssociationRequest)

        return True

    # Set Priority Lists (ie what data should be polled)
    def setPriorityLists(self):
        """Set Priority Lists (ie what data should be polled)
        Sends MDSSetPriorityListWave
        Receives the Confirmation
        """
        # Writes priority lists
        self.MDSSetPriorityListWave = self.Intellivue.writeData(
            "MDSSetPriorityListWAVE", self.desiredWaveParams
        )

        # Send priority lists
        self.socket.send(self.MDSSetPriorityListWave)
        print("Sent MDS Set Priority List Wave...")

        # Read in confirmation of changes
        no_confirmation = True
        while no_confirmation:
            message = self.socket.receive()
            message_type = self.Intellivue.getMessageType(message)

            # If Priority List Result, store message, advance script
            if message_type == "MDSSetPriorityListResult":
                PriorityListResult = self.Intellivue.readData(message)

                # If there are wave data objects, create a group for them
                if (
                    "NOM_ATTR_POLL_RTSA_PRIO_LIST"
                    in PriorityListResult["SetResult"]["AttributeList"]["AVAType"]
                ):
                    self.MDSSetPriorityListResultWave = PriorityListResult
                    print("Received MDS Set Priority List Result Wave.")

                no_confirmation = False

            # If MDSCreateEvent, then state failure to confirm
            elif message_type == "MDSCreateEvent":
                no_confirmation = False
                print("Failed to confirm setting of priority lists.")

        # Send Get Priority List
        self.socket.send(self.MDSGetPriorityList)
        print("Sent MDS Get Priority List...")

        no_priority_list = True
        while no_priority_list:
            message = self.socket.receive()
            message_type = self.Intellivue.getMessageType(message)

            if message_type == "MDSGetPriorityListResult":
                self.MDSGetPriorityListResult = self.Intellivue.readData(message)
                print("Received MDS Get Priority List Result.")
                no_priority_list = False

            elif message_type == "MDSCreateEvent":
                no_confirmation = 2
                print("Failed to confirm setting of priority lists.")
                no_priority_list = False

        return

    # Retrieve data from monitor
    def pullData(self):
        """Sends Extended Poll Requests for Numeric and Wave Data"""

        # Send Extended poll requests
        self.socket.send(self.MDSExtendedPollActionNumeric)
        self.socket.send(self.MDSExtendedPollActionWave)
        self.socket.send(self.MDSExtendedPollActionAlarm)
        print("Sent MDS Extended Poll Action for Numerics...")
        print("Sent MDS Extended Poll Action for Waves...")
        print("Sent MDS Extended Poll Action for Alarms...")

        # Keep track of 'Keep Alive' Messages
        keep_alive_messages = 1

        # Loop to check that connection still intact
        self.isConnected = True
        while self.isConnected:
            # Receive message
            message = self.socket.receive()
            message_type = self.Intellivue.getMessageType(message)

            # If abort, then break connection
            if message_type == "AssociationAbort":
                print("Data Collection Terminated.")
                self.socket.close()
                self.isConnected = False

            elif message_type == "RemoteOperationError":
                print("Error Message")

            # If keep alive response, print it
            elif message_type == "MDSSinglePollActionResult":
                print(str(datetime.datetime.now()), "Message Kept Alive!")

            # If data...
            elif (
                message_type == "MDSExtendedPollActionResult"
                or message_type == "LinkedMDSExtendedPollActionResult"
            ):
                # decode message
                decoded_message = self.Intellivue.readData(message)

                # If waves, save apprioriately
                if (
                    decoded_message["PollMdibDataReplyExt"]["Type"]["OIDType"]
                    == "NOM_MOC_VMO_METRIC_SA_RT"
                ):
                    self.parseVitalsWaveData(decoded_message)

                    # To store and output message times (in order to log when to send Keep Alive Messages)
                    if decoded_message["ROapdus"]["length"] > 100:
                        if (
                            "RelativeTime" in decoded_message["PollMdibDataReplyExt"]
                            and decoded_message["PollMdibDataReplyExt"]["sequence_no"]
                            != 0
                        ):
                            self.messageTimes.append(
                                (
                                    decoded_message["PollMdibDataReplyExt"][
                                        "RelativeTime"
                                    ]
                                    - self.relativeInitialTime
                                )
                                / 8000
                            )

                # If numerics, save apprioriately
                elif (
                    decoded_message["PollMdibDataReplyExt"]["Type"]["OIDType"]
                    == "NOM_MOC_VMO_METRIC_NU"
                ):
                    self.parseVitalsNumericsData(decoded_message)

                # If alarms, save apprioriately
                elif (
                    decoded_message["PollMdibDataReplyExt"]["Type"]["OIDType"]
                    == "NOM_MOC_VMO_AL_MON"
                ):
                    self.parseVitalsAlarmsData(decoded_message)

            else:
                print("Received " + message_type + ".")

            # Sends keep alive message if the most recently recorded time is greater than
            # the max value to keep alive (with a 5 second buffer)
            if self.messageTimes and self.messageTimes[-1] > (
                self.dataCollectionTime - 1
            ):
                self.isConnected = False
            elif self.messageTimes and self.messageTimes[-1] > (
                self.KeepAliveTime * keep_alive_messages - 5
            ):
                keep_alive_messages += 1
                self.socket.send(self.KeepAliveMessage)
                print(str(datetime.datetime.now()), "Sent Keep Alive Message...")

        return

    # Terminate the connection after done
    def endConnection(self):
        """Sends Release Request and waits for confirmation, closes udp port"""
        if not self.isConnected:
            return

        # Make pullData return
        self.isConnected = False

        # Send Release Request
        self.socket.send(self.ReleaseRequest)
        print("Sent Release Request...")

        not_refused = True
        while not_refused:
            message = self.socket.receive()
            message_type = self.Intellivue.getMessageType(message)

            if message_type == "ReleaseResponse" or message_type == "AssociationAbort":
                print("Connection with monitor released.")
                not_refused = False

        # Close UDP Port
        self.socket.close()

    # Reads in dict specified by ScaleRangeSpec16, returns a and b of y = ax + b
    def convertVitalsValues(self, ScaleRangeSpec16):
        """Converts values to physiological range using y = ax + b

        Parameters
        ----------
        ScaleRangeSpec16: dict
            specifies conversion factor by monitor


        Returns
        -------
        a, b: ints
            Scaling factors so that values can be converted
        """
        if type(ScaleRangeSpec16["upper_absolute_value"]["FLOATType"]) == str:
            return 1, 0

        else:
            x_range = (
                ScaleRangeSpec16["upper_scaled_value"]
                - ScaleRangeSpec16["lower_scaled_value"]
            )
            y_range = (
                ScaleRangeSpec16["upper_absolute_value"]["FLOATType"]
                - ScaleRangeSpec16["lower_absolute_value"]["FLOATType"]
            )
            a = y_range / x_range
            b = (
                ScaleRangeSpec16["lower_absolute_value"]["FLOATType"]
                - a * ScaleRangeSpec16["lower_scaled_value"]
            )

            return a, b

    # Parse relevant info from decoded wave message
    def parseVitalsWaveData(self, decoded_message):
        """Parse out important values from decoded_message to input into SaveProtocol

        Parameters
        ----------
        decoded_message: dict
            Dictionary created by IntellivueData class from parsed message

        """

        # Go through all of the Single Context Polls
        for singleContextPolls in decoded_message["PollMdibDataReplyExt"][
            "PollInfoList"
        ]:
            # Make sure that they are dicts (ie not length, count), and they aren't empty
            if (
                type(
                    decoded_message["PollMdibDataReplyExt"]["PollInfoList"][
                        singleContextPolls
                    ]
                )
                == dict
                and decoded_message["PollMdibDataReplyExt"]["PollInfoList"][
                    singleContextPolls
                ]["SingleContextPoll"]["poll_info"]["length"]
                > 0
            ):
                # Go through all of the Observation Polls (each data modality stored in separate observation poll)
                for observationPolls in decoded_message["PollMdibDataReplyExt"][
                    "PollInfoList"
                ][singleContextPolls]["SingleContextPoll"]["poll_info"]:
                    # Make sure that they are dicts (ie not length, count)
                    if (
                        type(
                            decoded_message["PollMdibDataReplyExt"]["PollInfoList"][
                                singleContextPolls
                            ]["SingleContextPoll"]["poll_info"][observationPolls]
                        )
                        == dict
                    ):
                        # If the message contains data regarding value conversion, units, and sampling freq, and is a compound value, store as defined below:
                        if (
                            "NOM_ATTR_SCALE_SPECN_I16"
                            in decoded_message["PollMdibDataReplyExt"]["PollInfoList"][
                                singleContextPolls
                            ]["SingleContextPoll"]["poll_info"][observationPolls][
                                "ObservationPoll"
                            ]["AttributeList"]["AVAType"]
                            and "NOM_ATTR_SA_CMPD_VAL_OBS"
                            in decoded_message["PollMdibDataReplyExt"]["PollInfoList"][
                                singleContextPolls
                            ]["SingleContextPoll"]["poll_info"][observationPolls][
                                "ObservationPoll"
                            ]["AttributeList"]["AVAType"]
                        ):
                            # Iterate through all the different data types (ie scada) in the compound value
                            for scada in decoded_message["PollMdibDataReplyExt"][
                                "PollInfoList"
                            ][singleContextPolls]["SingleContextPoll"]["poll_info"][
                                observationPolls
                            ]["ObservationPoll"]["AttributeList"]["AVAType"][
                                "NOM_ATTR_SA_CMPD_VAL_OBS"
                            ]["AttributeValue"]["SaObsValueCmp"]:
                                # Make sure that they are dicts (ie not length, count)
                                if (
                                    type(
                                        decoded_message["PollMdibDataReplyExt"][
                                            "PollInfoList"
                                        ][singleContextPolls]["SingleContextPoll"][
                                            "poll_info"
                                        ][observationPolls]["ObservationPoll"][
                                            "AttributeList"
                                        ]["AVAType"]["NOM_ATTR_SA_CMPD_VAL_OBS"][
                                            "AttributeValue"
                                        ]["SaObsValueCmp"][scada]
                                    )
                                    == dict
                                ):
                                    # Store label (in case of compound value, simply the scada label)
                                    label = decoded_message["PollMdibDataReplyExt"][
                                        "PollInfoList"
                                    ][singleContextPolls]["SingleContextPoll"][
                                        "poll_info"
                                    ][observationPolls]["ObservationPoll"][
                                        "AttributeList"
                                    ]["AVAType"]["NOM_ATTR_SA_CMPD_VAL_OBS"][
                                        "AttributeValue"
                                    ]["SaObsValueCmp"][scada]["SaObsValue"]["SCADAType"]

                                    # Sampling frequency
                                    fs = int(
                                        8000
                                        / decoded_message["PollMdibDataReplyExt"][
                                            "PollInfoList"
                                        ][singleContextPolls]["SingleContextPoll"][
                                            "poll_info"
                                        ][observationPolls]["ObservationPoll"][
                                            "AttributeList"
                                        ]["AVAType"]["NOM_ATTR_TIME_PD_SAMP"][
                                            "AttributeValue"
                                        ]["RelativeTime"]
                                    )

                                    # Initialize linear conversion values (ie y = mx + b)
                                    ValueConversion = self.convertVitalsValues(
                                        decoded_message["PollMdibDataReplyExt"][
                                            "PollInfoList"
                                        ][singleContextPolls]["SingleContextPoll"][
                                            "poll_info"
                                        ][observationPolls]["ObservationPoll"][
                                            "AttributeList"
                                        ]["AVAType"]["NOM_ATTR_SCALE_SPECN_I16"][
                                            "AttributeValue"
                                        ]["ScaleRangeSpec16"]
                                    )

                                    # Initialize units
                                    Units = decoded_message["PollMdibDataReplyExt"][
                                        "PollInfoList"
                                    ][singleContextPolls]["SingleContextPoll"][
                                        "poll_info"
                                    ][observationPolls]["ObservationPoll"][
                                        "AttributeList"
                                    ]["AVAType"]["NOM_ATTR_UNIT_CODE"][
                                        "AttributeValue"
                                    ]["UNITType"]

                                    # Inititialize Handle (to help uniquely identify scada)
                                    Handle = decoded_message["PollMdibDataReplyExt"][
                                        "PollInfoList"
                                    ][singleContextPolls]["SingleContextPoll"][
                                        "poll_info"
                                    ][observationPolls]["ObservationPoll"][
                                        "AttributeList"
                                    ]["AVAType"]["NOM_ATTR_ID_HANDLE"][
                                        "AttributeValue"
                                    ]["Handle"]

                                    # Initialize the extracted properties from Vitals Wave
                                    self.SaveProtocol.initializeVitalsWaveData(
                                        label, fs, ValueConversion, Units, Handle, label
                                    )

                        # If the message contains data regarding value conversion, units, and sampling freq, and is not compound, store it as defined below:
                        elif (
                            "NOM_ATTR_SCALE_SPECN_I16"
                            in decoded_message["PollMdibDataReplyExt"]["PollInfoList"][
                                singleContextPolls
                            ]["SingleContextPoll"]["poll_info"][observationPolls][
                                "ObservationPoll"
                            ]["AttributeList"]["AVAType"]
                        ):
                            # Store label (in case of normal value, is the TextId)
                            label = decoded_message["PollMdibDataReplyExt"][
                                "PollInfoList"
                            ][singleContextPolls]["SingleContextPoll"]["poll_info"][
                                observationPolls
                            ]["ObservationPoll"]["AttributeList"]["AVAType"][
                                "NOM_ATTR_ID_LABEL"
                            ]["AttributeValue"]["TextId"]

                            # Sampling frequency
                            fs = int(
                                8000
                                / decoded_message["PollMdibDataReplyExt"][
                                    "PollInfoList"
                                ][singleContextPolls]["SingleContextPoll"]["poll_info"][
                                    observationPolls
                                ]["ObservationPoll"]["AttributeList"]["AVAType"][
                                    "NOM_ATTR_TIME_PD_SAMP"
                                ]["AttributeValue"]["RelativeTime"]
                            )

                            # Initialize linear conversion values (ie y = mx + b)
                            ValueConversion = self.convertVitalsValues(
                                decoded_message["PollMdibDataReplyExt"]["PollInfoList"][
                                    singleContextPolls
                                ]["SingleContextPoll"]["poll_info"][observationPolls][
                                    "ObservationPoll"
                                ]["AttributeList"]["AVAType"][
                                    "NOM_ATTR_SCALE_SPECN_I16"
                                ]["AttributeValue"]["ScaleRangeSpec16"]
                            )

                            # Initialize units
                            Units = decoded_message["PollMdibDataReplyExt"][
                                "PollInfoList"
                            ][singleContextPolls]["SingleContextPoll"]["poll_info"][
                                observationPolls
                            ]["ObservationPoll"]["AttributeList"]["AVAType"][
                                "NOM_ATTR_UNIT_CODE"
                            ]["AttributeValue"]["UNITType"]

                            # Inititialize Handle (to help uniquely identify scada)
                            Handle = decoded_message["PollMdibDataReplyExt"][
                                "PollInfoList"
                            ][singleContextPolls]["SingleContextPoll"]["poll_info"][
                                observationPolls
                            ]["ObservationPoll"]["AttributeList"]["AVAType"][
                                "NOM_ATTR_ID_HANDLE"
                            ]["AttributeValue"]["Handle"]

                            # Initialize the extracted properties from Vitals Wave
                            self.SaveProtocol.initializeVitalsWaveData(
                                label, fs, ValueConversion, Units, Handle, label
                            )

                        # If the message contains data, save it
                        if (
                            "NOM_ATTR_SA_VAL_OBS"
                            in decoded_message["PollMdibDataReplyExt"]["PollInfoList"][
                                singleContextPolls
                            ]["SingleContextPoll"]["poll_info"][observationPolls][
                                "ObservationPoll"
                            ]["AttributeList"]["AVAType"]
                        ):
                            # Determine label based on SCADA Type and Handle
                            for dataTypes in self.SaveProtocol._VitalsWaveInfo:
                                # If label identified (ie handle and SCADA type match Text ID)...
                                if (
                                    self.SaveProtocol._VitalsWaveInfo[dataTypes][
                                        "Handle"
                                    ]
                                    == decoded_message["PollMdibDataReplyExt"][
                                        "PollInfoList"
                                    ][singleContextPolls]["SingleContextPoll"][
                                        "poll_info"
                                    ][observationPolls]["ObservationPoll"]["Handle"]
                                    and decoded_message["PollMdibDataReplyExt"][
                                        "PollInfoList"
                                    ][singleContextPolls]["SingleContextPoll"][
                                        "poll_info"
                                    ][observationPolls]["ObservationPoll"][
                                        "AttributeList"
                                    ]["AVAType"]["NOM_ATTR_SA_VAL_OBS"][
                                        "AttributeValue"
                                    ]["SaObsValue"]["SCADAType"]
                                    in self.Intellivue.DataKeys["PhysioKeys"][dataTypes]
                                ):
                                    # Set label appropriately
                                    label = dataTypes

                                    # Create temporary data array
                                    temp_array = np.array(
                                        decoded_message["PollMdibDataReplyExt"][
                                            "PollInfoList"
                                        ][singleContextPolls]["SingleContextPoll"][
                                            "poll_info"
                                        ][observationPolls]["ObservationPoll"][
                                            "AttributeList"
                                        ]["AVAType"]["NOM_ATTR_SA_VAL_OBS"][
                                            "AttributeValue"
                                        ]["SaObsValue"]["PhysioValue"]["VariableData"][
                                            "value"
                                        ]
                                    )

                                    # Timestamp
                                    relativeTime = decoded_message[
                                        "PollMdibDataReplyExt"
                                    ]["RelativeTime"]

                                    # Save Vitals Wave Data
                                    self.SaveProtocol.saveVitalsWaveData(
                                        label, temp_array, relativeTime
                                    )

                        # If the message contains compound data, save it
                        if (
                            "NOM_ATTR_SA_CMPD_VAL_OBS"
                            in decoded_message["PollMdibDataReplyExt"]["PollInfoList"][
                                singleContextPolls
                            ]["SingleContextPoll"]["poll_info"][observationPolls][
                                "ObservationPoll"
                            ]["AttributeList"]["AVAType"]
                        ):
                            # Determine label based on SCADA Type and Handle
                            for dataTypes in self.SaveProtocol._VitalsWaveInfo:
                                # If handle matches...
                                if (
                                    self.SaveProtocol._VitalsWaveInfo[dataTypes][
                                        "Handle"
                                    ]
                                    == decoded_message["PollMdibDataReplyExt"][
                                        "PollInfoList"
                                    ][singleContextPolls]["SingleContextPoll"][
                                        "poll_info"
                                    ][observationPolls]["ObservationPoll"]["Handle"]
                                ):
                                    # iterate through all the compound values
                                    for saObsValues in decoded_message[
                                        "PollMdibDataReplyExt"
                                    ]["PollInfoList"][singleContextPolls][
                                        "SingleContextPoll"
                                    ]["poll_info"][observationPolls]["ObservationPoll"][
                                        "AttributeList"
                                    ]["AVAType"]["NOM_ATTR_SA_CMPD_VAL_OBS"][
                                        "AttributeValue"
                                    ]["SaObsValueCmp"]:
                                        # iterate through dictionaries only (ie not count, length)
                                        if (
                                            type(
                                                decoded_message["PollMdibDataReplyExt"][
                                                    "PollInfoList"
                                                ][singleContextPolls][
                                                    "SingleContextPoll"
                                                ]["poll_info"][observationPolls][
                                                    "ObservationPoll"
                                                ]["AttributeList"]["AVAType"][
                                                    "NOM_ATTR_SA_CMPD_VAL_OBS"
                                                ]["AttributeValue"]["SaObsValueCmp"][
                                                    saObsValues
                                                ]
                                            )
                                            == dict
                                        ):
                                            # Make sure scada type matches data type
                                            if (
                                                decoded_message["PollMdibDataReplyExt"][
                                                    "PollInfoList"
                                                ][singleContextPolls][
                                                    "SingleContextPoll"
                                                ]["poll_info"][observationPolls][
                                                    "ObservationPoll"
                                                ]["AttributeList"]["AVAType"][
                                                    "NOM_ATTR_SA_CMPD_VAL_OBS"
                                                ]["AttributeValue"]["SaObsValueCmp"][
                                                    saObsValues
                                                ]["SaObsValue"]["SCADAType"]
                                                == dataTypes
                                            ):
                                                # Set label appropriately
                                                label = dataTypes

                                                # Create temporary data array
                                                temp_array = np.array(
                                                    decoded_message[
                                                        "PollMdibDataReplyExt"
                                                    ]["PollInfoList"][
                                                        singleContextPolls
                                                    ]["SingleContextPoll"]["poll_info"][
                                                        observationPolls
                                                    ]["ObservationPoll"][
                                                        "AttributeList"
                                                    ]["AVAType"][
                                                        "NOM_ATTR_SA_CMPD_VAL_OBS"
                                                    ]["AttributeValue"][
                                                        "SaObsValueCmp"
                                                    ][saObsValues]["SaObsValue"][
                                                        "PhysioValue"
                                                    ]["VariableData"]["value"]
                                                ).T

                                                # Timestamp
                                                relativeTime = decoded_message[
                                                    "PollMdibDataReplyExt"
                                                ]["RelativeTime"]

                                                # Save Vitals Wave Data
                                                self.SaveProtocol.saveVitalsWaveData(
                                                    label, temp_array, relativeTime
                                                )

    # Parse relevant info from decoded numeric message
    def parseVitalsNumericsData(self, decoded_message):
        """Parse out important values from decoded_message to input into SaveProtocol

        Parameters
        ----------
        decoded_message: dict
            Dictionary created by IntellivueData class from parsed message

        """
        # Go through all of the Single Context Polls
        for singleContextPolls in decoded_message["PollMdibDataReplyExt"][
            "PollInfoList"
        ]:
            # Make sure that they are dicts (ie not length, count), and they aren't empty
            if (
                type(
                    decoded_message["PollMdibDataReplyExt"]["PollInfoList"][
                        singleContextPolls
                    ]
                )
                == dict
                and decoded_message["PollMdibDataReplyExt"]["PollInfoList"][
                    singleContextPolls
                ]["SingleContextPoll"]["poll_info"]["length"]
                > 0
            ):
                # Go through all of the Observation Polls
                for observationPolls in decoded_message["PollMdibDataReplyExt"][
                    "PollInfoList"
                ][singleContextPolls]["SingleContextPoll"]["poll_info"]:
                    # Make sure that they are dicts (ie not length, count)
                    if (
                        type(
                            decoded_message["PollMdibDataReplyExt"]["PollInfoList"][
                                singleContextPolls
                            ]["SingleContextPoll"]["poll_info"][observationPolls]
                        )
                        == dict
                    ):
                        # If there is data, store it
                        if (
                            "NOM_ATTR_NU_VAL_OBS"
                            in decoded_message["PollMdibDataReplyExt"]["PollInfoList"][
                                singleContextPolls
                            ]["SingleContextPoll"]["poll_info"][observationPolls][
                                "ObservationPoll"
                            ]["AttributeList"]["AVAType"]
                        ):
                            # Unique label
                            label = decoded_message["PollMdibDataReplyExt"][
                                "PollInfoList"
                            ][singleContextPolls]["SingleContextPoll"]["poll_info"][
                                observationPolls
                            ]["ObservationPoll"]["AttributeList"]["AVAType"][
                                "NOM_ATTR_ID_LABEL"
                            ]["AttributeValue"]["TextId"]

                            # Ensure label is a string
                            label = str(label)

                            # Units
                            Units = decoded_message["PollMdibDataReplyExt"][
                                "PollInfoList"
                            ][singleContextPolls]["SingleContextPoll"]["poll_info"][
                                observationPolls
                            ]["ObservationPoll"]["AttributeList"]["AVAType"][
                                "NOM_ATTR_NU_VAL_OBS"
                            ]["AttributeValue"]["NuObsValue"]["UNITType"]

                            # Initialize attributes
                            self.SaveProtocol.initializeVitalsNumericsData(label, Units)

                            # Timestamp
                            relativeTime = decoded_message["PollMdibDataReplyExt"][
                                "RelativeTime"
                            ]

                            # temporary values
                            temp_value = decoded_message["PollMdibDataReplyExt"][
                                "PollInfoList"
                            ][singleContextPolls]["SingleContextPoll"]["poll_info"][
                                observationPolls
                            ]["ObservationPoll"]["AttributeList"]["AVAType"][
                                "NOM_ATTR_NU_VAL_OBS"
                            ]["AttributeValue"]["NuObsValue"]["FLOATType"]

                            # save data
                            self.SaveProtocol.saveVitalsNumericsData(
                                label, temp_value, relativeTime
                            )

                        # If compound data type...
                        if (
                            "NOM_ATTR_NU_CMPD_VAL_OBS"
                            in decoded_message["PollMdibDataReplyExt"]["PollInfoList"][
                                singleContextPolls
                            ]["SingleContextPoll"]["poll_info"][observationPolls][
                                "ObservationPoll"
                            ]["AttributeList"]["AVAType"]
                        ):
                            # NOT unique label (each value within the compound value has it)
                            label = decoded_message["PollMdibDataReplyExt"][
                                "PollInfoList"
                            ][singleContextPolls]["SingleContextPoll"]["poll_info"][
                                observationPolls
                            ]["ObservationPoll"]["AttributeList"]["AVAType"][
                                "NOM_ATTR_ID_LABEL"
                            ]["AttributeValue"]["TextId"]

                            # Store temporary time values
                            relativeTime = decoded_message["PollMdibDataReplyExt"][
                                "RelativeTime"
                            ]

                            # For each individual value within the compound
                            for scada in decoded_message["PollMdibDataReplyExt"][
                                "PollInfoList"
                            ][singleContextPolls]["SingleContextPoll"]["poll_info"][
                                observationPolls
                            ]["ObservationPoll"]["AttributeList"]["AVAType"][
                                "NOM_ATTR_NU_CMPD_VAL_OBS"
                            ]["AttributeValue"]["NuObsValCmp"]:
                                # Make sure to iterate through dicts (ie not count, length)
                                if (
                                    type(
                                        decoded_message["PollMdibDataReplyExt"][
                                            "PollInfoList"
                                        ][singleContextPolls]["SingleContextPoll"][
                                            "poll_info"
                                        ][observationPolls]["ObservationPoll"][
                                            "AttributeList"
                                        ]["AVAType"]["NOM_ATTR_NU_CMPD_VAL_OBS"][
                                            "AttributeValue"
                                        ]["NuObsValCmp"][scada]
                                    )
                                    == dict
                                ):
                                    # Create unique scada_label which has both TextID and scada_type
                                    scada_type = decoded_message[
                                        "PollMdibDataReplyExt"
                                    ]["PollInfoList"][singleContextPolls][
                                        "SingleContextPoll"
                                    ]["poll_info"][observationPolls]["ObservationPoll"][
                                        "AttributeList"
                                    ]["AVAType"]["NOM_ATTR_NU_CMPD_VAL_OBS"][
                                        "AttributeValue"
                                    ]["NuObsValCmp"][scada]["NuObsValue"]["SCADAType"]
                                    scada_label = (
                                        label + "_" + scada_type.split("_")[-1]
                                    )

                                    Units = decoded_message["PollMdibDataReplyExt"][
                                        "PollInfoList"
                                    ][singleContextPolls]["SingleContextPoll"][
                                        "poll_info"
                                    ][observationPolls]["ObservationPoll"][
                                        "AttributeList"
                                    ]["AVAType"]["NOM_ATTR_NU_CMPD_VAL_OBS"][
                                        "AttributeValue"
                                    ]["NuObsValCmp"][scada]["NuObsValue"]["UNITType"]

                                    self.SaveProtocol.initializeVitalsNumericsData(
                                        scada_label, Units
                                    )

                                    # If everything initialized, start writing data

                                    # temporary values
                                    temp_value = decoded_message[
                                        "PollMdibDataReplyExt"
                                    ]["PollInfoList"][singleContextPolls][
                                        "SingleContextPoll"
                                    ]["poll_info"][observationPolls]["ObservationPoll"][
                                        "AttributeList"
                                    ]["AVAType"]["NOM_ATTR_NU_CMPD_VAL_OBS"][
                                        "AttributeValue"
                                    ]["NuObsValCmp"][scada]["NuObsValue"]["FLOATType"]

                                    self.SaveProtocol.saveVitalsNumericsData(
                                        scada_label, temp_value, relativeTime
                                    )

    # Parse relevant info from decoded alarm message
    def parseVitalsAlarmsData(self, decoded_message):
        """Parse out important values from decoded_message to input into SaveProtocol

        Parameters
        ----------
        decoded_message: dict
            Dictionary created by IntellivueData class from parsed message

        """
        # Go through all of the Single Context Polls
        for singleContextPolls in decoded_message["PollMdibDataReplyExt"][
            "PollInfoList"
        ]:
            # Make sure that they are dicts (ie not length, count), and they aren't empty
            if (
                type(
                    decoded_message["PollMdibDataReplyExt"]["PollInfoList"][
                        singleContextPolls
                    ]
                )
                == dict
                and decoded_message["PollMdibDataReplyExt"]["PollInfoList"][
                    singleContextPolls
                ]["SingleContextPoll"]["poll_info"]["length"]
                > 0
            ):
                # Go through all of the Observation Polls (each data modality stored in separate observation poll)
                for observationPolls in decoded_message["PollMdibDataReplyExt"][
                    "PollInfoList"
                ][singleContextPolls]["SingleContextPoll"]["poll_info"]:
                    # Make sure that they are dicts (ie not length, count)
                    if (
                        type(
                            decoded_message["PollMdibDataReplyExt"]["PollInfoList"][
                                singleContextPolls
                            ]["SingleContextPoll"]["poll_info"][observationPolls]
                        )
                        == dict
                    ):
                        # Timestamp
                        relativeTime = decoded_message["PollMdibDataReplyExt"][
                            "RelativeTime"
                        ]

                        # If the message active patient alarm data, store it
                        if (
                            "NOM_ATTR_AL_MON_P_AL_LIST"
                            in decoded_message["PollMdibDataReplyExt"]["PollInfoList"][
                                singleContextPolls
                            ]["SingleContextPoll"]["poll_info"][observationPolls][
                                "ObservationPoll"
                            ]["AttributeList"]["AVAType"]
                        ):
                            i = 0

                            # Iterate through all the different data types (ie scada) in the compound value
                            for devAlarm in decoded_message["PollMdibDataReplyExt"][
                                "PollInfoList"
                            ][singleContextPolls]["SingleContextPoll"]["poll_info"][
                                observationPolls
                            ]["ObservationPoll"]["AttributeList"]["AVAType"][
                                "NOM_ATTR_AL_MON_P_AL_LIST"
                            ]["AttributeValue"]["DevAlarmList"]:
                                # Make sure that they are dicts (ie not length, count)
                                if (
                                    type(
                                        decoded_message["PollMdibDataReplyExt"][
                                            "PollInfoList"
                                        ][singleContextPolls]["SingleContextPoll"][
                                            "poll_info"
                                        ][observationPolls]["ObservationPoll"][
                                            "AttributeList"
                                        ]["AVAType"]["NOM_ATTR_AL_MON_P_AL_LIST"][
                                            "AttributeValue"
                                        ]["DevAlarmList"][devAlarm]
                                    )
                                    == dict
                                ):
                                    # Initialize entries
                                    alarmType = "Patient"
                                    alarmNum = i
                                    alarmEntry = alarmType + "_" + str(alarmNum)

                                    # Obtain code
                                    code = decoded_message["PollMdibDataReplyExt"][
                                        "PollInfoList"
                                    ][singleContextPolls]["SingleContextPoll"][
                                        "poll_info"
                                    ][observationPolls]["ObservationPoll"][
                                        "AttributeList"
                                    ]["AVAType"]["NOM_ATTR_AL_MON_P_AL_LIST"][
                                        "AttributeValue"
                                    ]["DevAlarmList"][devAlarm]["DevAlarmEntry"][
                                        "al_code"
                                    ]  # .split('NOM_EVT_')[1]

                                    # Obtain source
                                    source = decoded_message["PollMdibDataReplyExt"][
                                        "PollInfoList"
                                    ][singleContextPolls]["SingleContextPoll"][
                                        "poll_info"
                                    ][observationPolls]["ObservationPoll"][
                                        "AttributeList"
                                    ]["AVAType"]["NOM_ATTR_AL_MON_P_AL_LIST"][
                                        "AttributeValue"
                                    ]["DevAlarmList"][devAlarm]["DevAlarmEntry"][
                                        "al_source"
                                    ]  # .split('NOM_')[1]

                                    # Obtain alarmType
                                    alarmType = decoded_message["PollMdibDataReplyExt"][
                                        "PollInfoList"
                                    ][singleContextPolls]["SingleContextPoll"][
                                        "poll_info"
                                    ][observationPolls]["ObservationPoll"][
                                        "AttributeList"
                                    ]["AVAType"]["NOM_ATTR_AL_MON_P_AL_LIST"][
                                        "AttributeValue"
                                    ]["DevAlarmList"][devAlarm]["DevAlarmEntry"][
                                        "AlertType"
                                    ]  # .split('_')[0] + '_P'

                                    # Obtain alarmState
                                    state = decoded_message["PollMdibDataReplyExt"][
                                        "PollInfoList"
                                    ][singleContextPolls]["SingleContextPoll"][
                                        "poll_info"
                                    ][observationPolls]["ObservationPoll"][
                                        "AttributeList"
                                    ]["AVAType"]["NOM_ATTR_AL_MON_P_AL_LIST"][
                                        "AttributeValue"
                                    ]["DevAlarmList"][devAlarm]["DevAlarmEntry"][
                                        "AlertState"
                                    ]  # .split('AL_')[1]

                                    # Obtain alarmString
                                    alarmString = decoded_message[
                                        "PollMdibDataReplyExt"
                                    ]["PollInfoList"][singleContextPolls][
                                        "SingleContextPoll"
                                    ]["poll_info"][observationPolls]["ObservationPoll"][
                                        "AttributeList"
                                    ]["AVAType"]["NOM_ATTR_AL_MON_P_AL_LIST"][
                                        "AttributeValue"
                                    ]["DevAlarmList"][devAlarm]["DevAlarmEntry"][
                                        "StrAlMonInfo"
                                    ]["String"]["value"]

                                    # Save data
                                    self.SaveProtocol.saveVitalsAlarmsData(
                                        relativeTime,
                                        alarmEntry,
                                        code,
                                        source,
                                        alarmType,
                                        state,
                                        alarmString,
                                    )

                                    i += 1

                        # If the patient contains active technical alarms, store it
                        if (
                            "NOM_ATTR_AL_MON_T_AL_LIST"
                            in decoded_message["PollMdibDataReplyExt"]["PollInfoList"][
                                singleContextPolls
                            ]["SingleContextPoll"]["poll_info"][observationPolls][
                                "ObservationPoll"
                            ]["AttributeList"]["AVAType"]
                        ):
                            i = 0

                            # Iterate through all the different data types (ie scada) in the compound value
                            for devAlarm in decoded_message["PollMdibDataReplyExt"][
                                "PollInfoList"
                            ][singleContextPolls]["SingleContextPoll"]["poll_info"][
                                observationPolls
                            ]["ObservationPoll"]["AttributeList"]["AVAType"][
                                "NOM_ATTR_AL_MON_T_AL_LIST"
                            ]["AttributeValue"]["DevAlarmList"]:
                                # Make sure that they are dicts (ie not length, count)
                                if (
                                    type(
                                        decoded_message["PollMdibDataReplyExt"][
                                            "PollInfoList"
                                        ][singleContextPolls]["SingleContextPoll"][
                                            "poll_info"
                                        ][observationPolls]["ObservationPoll"][
                                            "AttributeList"
                                        ]["AVAType"]["NOM_ATTR_AL_MON_T_AL_LIST"][
                                            "AttributeValue"
                                        ]["DevAlarmList"][devAlarm]
                                    )
                                    == dict
                                ):
                                    # Initialize entries
                                    alarmType = "Technical"
                                    alarmNum = i
                                    alarmEntry = alarmType + "_" + str(alarmNum)

                                    # Obtain code
                                    code = decoded_message["PollMdibDataReplyExt"][
                                        "PollInfoList"
                                    ][singleContextPolls]["SingleContextPoll"][
                                        "poll_info"
                                    ][observationPolls]["ObservationPoll"][
                                        "AttributeList"
                                    ]["AVAType"]["NOM_ATTR_AL_MON_T_AL_LIST"][
                                        "AttributeValue"
                                    ]["DevAlarmList"][devAlarm]["DevAlarmEntry"][
                                        "al_code"
                                    ]  # .split('NOM_EVT_')[1]

                                    # Obtain source
                                    source = decoded_message["PollMdibDataReplyExt"][
                                        "PollInfoList"
                                    ][singleContextPolls]["SingleContextPoll"][
                                        "poll_info"
                                    ][observationPolls]["ObservationPoll"][
                                        "AttributeList"
                                    ]["AVAType"]["NOM_ATTR_AL_MON_T_AL_LIST"][
                                        "AttributeValue"
                                    ]["DevAlarmList"][devAlarm]["DevAlarmEntry"][
                                        "al_source"
                                    ]  # .split('NOM_')[1]

                                    # Obtain alarmType
                                    alarmType = decoded_message["PollMdibDataReplyExt"][
                                        "PollInfoList"
                                    ][singleContextPolls]["SingleContextPoll"][
                                        "poll_info"
                                    ][observationPolls]["ObservationPoll"][
                                        "AttributeList"
                                    ]["AVAType"]["NOM_ATTR_AL_MON_T_AL_LIST"][
                                        "AttributeValue"
                                    ]["DevAlarmList"][devAlarm]["DevAlarmEntry"][
                                        "AlertType"
                                    ]  # .split('_')[0] + '_P'

                                    # Obtain alarmState
                                    state = decoded_message["PollMdibDataReplyExt"][
                                        "PollInfoList"
                                    ][singleContextPolls]["SingleContextPoll"][
                                        "poll_info"
                                    ][observationPolls]["ObservationPoll"][
                                        "AttributeList"
                                    ]["AVAType"]["NOM_ATTR_AL_MON_T_AL_LIST"][
                                        "AttributeValue"
                                    ]["DevAlarmList"][devAlarm]["DevAlarmEntry"][
                                        "AlertState"
                                    ]  # .split('AL_')[1]

                                    # Obtain alarmString
                                    alarmString = decoded_message[
                                        "PollMdibDataReplyExt"
                                    ]["PollInfoList"][singleContextPolls][
                                        "SingleContextPoll"
                                    ]["poll_info"][observationPolls]["ObservationPoll"][
                                        "AttributeList"
                                    ]["AVAType"]["NOM_ATTR_AL_MON_T_AL_LIST"][
                                        "AttributeValue"
                                    ]["DevAlarmList"][devAlarm]["DevAlarmEntry"][
                                        "StrAlMonInfo"
                                    ]["String"]["value"]

                                    # Save data
                                    self.SaveProtocol.saveVitalsAlarmsData(
                                        relativeTime,
                                        alarmEntry,
                                        code,
                                        source,
                                        alarmType,
                                        state,
                                        alarmString,
                                    )

                                    i += 1


if __name__ == "__main__":
    pass
