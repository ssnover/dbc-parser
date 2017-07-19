#! python3

"""
    File:       dbcParser.py
    Created:    03/29/2017

    This Python script contains classes for describing the contents of a CAN
    database file. Given a .dbc file, it will parse it into objects in memory
    and generate a C header file for use by the Network Manager embedded
    firmware application for packaging and unpackaging data in CAN data frames.

    Before editing, please read the EVT Wiki page describing the objects in a
    CAN Database, located here:
        https://wiki.rit.edu/display/EVT/CAN+Database
"""

import re

__regex_pattern__ = re.compile(r""" SG_ (?P<name>.*) : (?P<start_bit>[0-9]{1,2})\|(?P<length>[0-9]{1,2})@(?P<format>[0-1])(?P<type>[+-]) \((?P<factor>.*),(?P<offset>.*)\) \[(?P<min>.*)\|(?P<max>.*)\] "(?P<unit>.*)"(\s{1,2})(?P<rx_nodes>.*)""")


class CANDatabase:
    """
    Object to hold all CAN messages in a network as defined by the DBC file.
    """

    # Private Properties
    _name = ""
    _dbcPath = ""
    _comment = ""
    _messages = list()
    _txNodes = list()
    _extended = False
    _attributes = list()
    _iter_index = 0

    def __init__(self, dbc_path):
        """
        Constructor for the CAN Database.

        Arguments:
         - dbcPath: The file path to .dbc file.
        """
        self._dbcPath = dbc_path

    def __iter__(self):
        """
        Defined to make the object iterable.
        """
        return self

    def __next__(self):
        """
        Get the next iterable in the CANMessage list.
        """
        if self._iter_index == len(self._messages):
            self._iter_index = 0
            raise StopIteration
        self._iter_index += 1
        return self._messages[self._iter_index-1]

    def Load(self):
        """
        Opens the DBC file and parses its contents.
        """
        try:
            file = open(self._dbcPath)
        except OSError:
            print("Invalid file path specified.")
            print(self._dbcPath)
            return

        building_message = False
        can_msg = None

        line_number = 0
        for line in file:
            line = line.rstrip('\n')
            line_number += 1  # keep track of the line number for error reporting

            if line.startswith("BU_:"):
                self._parseTransmittingNodes(line)

            elif line.startswith("BO_"):
                can_msg = self._parseMessageHeader(line)
                building_message = True

            elif line.startswith(" SG_") and building_message:
                can_msg.AddSignal(self._parseSignalEntry(line))

            elif line == "":
                if building_message:
                    building_message = False
                    self._messages += [can_msg]
                    can_msg.UpdateSubscribers()
                    can_msg = None

            elif line.startswith("VAL_"):
                val_components = valueLineSplit(line)
                new_value_name = val_components[2]
                new_value_canID = int(val_components[1], 16)
                # Tuple: (Name, CAN ID, Item Pairs)
                new_value = (new_value_name, new_value_canID, list())

                pairs = val_components[3:]
                for i in range(0, len(pairs), 2):
                    try:
                        # add item value/name pairs to list in new_value tuple
                        item_value = int(pairs[i])
                        item_name = pairs[i+1]
                        new_value[2].append((item_value, item_name))
                    except IndexError:
                        print("Invalid value: " + new_value_name + 
                              ". Found on line " + str(line_number) + '.')
                        return None

                for message in self:
                    if message.CANID() == new_value[1]:
                        message.AddValue(new_value)
                        break

            # parse attributes
            elif line.startswith("BA_DEF_ BO_"):
                components = line.split(' ')
                # warning: indices are one higher than they appear to be because of double space in line
                attr_name = components[3].strip('"')
                attr_type = components[4]
                attr_min = components[5]
                attr_max = components[6].rstrip(';')

                new_attr = (attr_name, attr_type, attr_min, attr_max)
                self._attributes.append(new_attr)

            elif line.startswith("BA_ "):
                components = line.split(' ')
                attr_name = components[1].strip('"')
                attr_msgID = int(components[3])
                attr_val = components[4].rstrip(';')

                new_attr = (attr_name, attr_val)

                for message in self:
                    if message.CANID() == attr_msgID:
                        message.AddAttribute(new_attr)
                        break

            elif line.startswith("CM_"):
                components = line.split(' ')
                if len(components) <= 2:
                    break
                for message in self:
                    if message.CANID() == int(components[2]):
                        for signal in message:
                            if signal.Name() == components[3]:
                                comment_str = ''
                                for each in components[4:]:
                                    comment_str += each
                                signal.AddComment(comment_str)
                                break
                    break

        self._iter_index = 0

        return self

    def Name(self):
        """
        Gets the CAN Database's name.
        """
        return self._name

    def Messages(self):
        """
        Gets the list of CANMessage objects.
        """
        return self._messages

    def _parseTransmittingNodes(self, line):
        """
        Takes a string and parses the name of transmitting nodes in the CAN bus
        from it.
        """
        items = line.split(' ')
        for each in items:
            if each == "BU_:":
                pass
            else:
                self._txNodes += [each]

        return

    def _parseMessageHeader(self, line):
        """
        Creates a signal-less CANMessage object from the header line.
        """
        items = line.split(' ')
        msg_id = int(items[1])
        msg_name = items[2].rstrip(':')
        msg_dlc = int(items[3])
        msg_tx = items[4].rstrip('\n')

        return CANMessage(msg_id, msg_name, msg_dlc, msg_tx)

    def _parseSignalEntry(self, line):
        """
        Creates a CANSignal object from DBC file information.

        The Regex used is compiled once in order to save time for the numerous
        signals being parsed.
        """
        result = __regex_pattern__.match(line)

        name = result.group('name')
        start_bit = int(result.group('start_bit'))
        length = int(result.group('length'))
        sig_format = int(result.group('format'))
        sig_type = result.group('type')
        factor = int(result.group('factor'))
        offset = int(result.group('offset'))
        minimum = int(result.group('min'))
        maximum = int(result.group('max'))
        unit = result.group('unit')
        rx_nodes = result.group('rx_nodes').split(',')

        return CANSignal(name, sig_type, sig_format, start_bit, length, offset,
                         factor, minimum, maximum, unit, rx_nodes)


class CANMessage:
    """
    Contains information on a message's ID, length in bytes, transmitting node,
    and the signals it contains.
    """

    def __init__(self, msg_id, msg_name, msg_dlc, msg_tx):
        """
        Constructor.
        """
        self._canID = msg_id
        self._name = msg_name
        self._dlc = msg_dlc
        self._txNode = msg_tx
        self._idType = None
        self._comment = ""
        self._signals = list()
        self._attributes = list()
        self._iter_index = 0
        self._subscribers = list()

    def __iter__(self):
        """
        Defined to make the object iterable.
        """
        self._iter_index = 0
        return self

    def __next__(self):
        """
        Defines the next CANSignal object to be returned in an iteration.
        """
        if self._iter_index == len(self._signals):
            self._iter_index = 0
            raise StopIteration
        self._iter_index += 1
        return self._signals[self._iter_index-1]

    def AddSignal(self, signal):
        """
        Takes a CANSignal object and adds it to the list of signals.
        """
        self._signals += [signal]
        return self

    def Signals(self):
        """
        Gets the signals in a CANMessage object.
        """
        return self._signals

    def SetComment(self, comment_str):
        """
        Sets the Comment property for the CANMessage.
        """
        self._comment = comment_str

        return self

    def CANID(self):
        """
        Gets the message's CAN ID.
        """
        return self._canID

    def AddValue(self, value_tuple):
        """
        Adds a enumerated value mapping to the appropriate signal.
        """
        for signal in self:
            if signal.Name() == value_tuple[0]:
                signal.SetValues(value_tuple[2])
                break
        return self

    def AddAttribute(self, attr_tuple):
        """
        Adds an attribute to the message.
        """
        self._attributes.append(attr_tuple)
        return self

    def Attributes(self):
        return self._attributes

    def Name(self):
        return self._name

    def TransmittingNode(self):
        return self._txNode

    def DLC(self):
        return self._dlc

    def UpdateSubscribers(self):
        """
        Iterates through signals in the message to note all of the receiving
        nodes subscribed to the message.
        """
        for signal in self:
            nodes = signal.RxNodes()
            for each in nodes:
                if each not in self._subscribers:
                    self._subscribers += [each]

        return self


class CANSignal:
    """
    Contains information describing a signal in a CAN message.
    """

    def __init__(self, name, sigtype, sigformat, startbit, length, offset, factor,
                 minVal, maxVal, unit, rx_nodes):
        """
        Constructor.
        """
        self._name = name
        self._type = sigtype
        self._format = sigformat
        self._startbit = startbit
        self._length = length
        self._offset = offset
        self._factor = factor
        self._minVal = minVal
        self._maxVal = maxVal
        self._units = unit
        self._values = list()
        self._comment = ""
        self._rx_nodes = rx_nodes

    def __lt__(self, other):
        return self._startbit < other._startbit

    def Name(self):
        """
        Gets the name of the CANSignal.
        """
        return self._name

    def SetValues(self, values_lst):
        """
        Sets the enumerated value map for the signal's data.
        """
        self._values = values_lst
        return self

    def Length(self):
        return self._length

    def SignType(self):
        return self._type

    def AddComment(self, cm_str):
        self._comment = cm_str

    def ReadComment(self):
        return self._comment

    def RxNodes(self):
        return self._rx_nodes


def valueLineSplit(line):
    """
    Custom split function for splitting up the components of a value line.

    Could not use normal String.split(' ') due to spaces in some of the value
    name strings.
    """
    components = list()
    part = ""
    in_quotes = False
    for ch in line:
        if ch == ' ' and not in_quotes:
            components.append(part)
            part = ""
        elif ch == '"' and not in_quotes:
            in_quotes = True
        elif ch == '"' and in_quotes:
            in_quotes = False
        else:
            part += ch
    return components


def main():
    """
    Opens a DBC file and parses it into a CANDatabase object and uses the
    information to generate a C header file for the Network Manager
    application.
    """
    file = "EVT_CAN.dbc"
    candb = CANDatabase(file)
    candb.Load()
    input()

if __name__ == "__main__":
    main()
