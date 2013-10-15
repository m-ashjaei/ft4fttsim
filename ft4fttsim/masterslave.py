# author: David Gessner <davidges@gmail.com>

from networking import NetworkDevice, Message
from ethernet import Ethernet
from SimPy.Simulation import passivate, now, activate, hold


class Master(NetworkDevice):
    """
    Class for FTT masters.
    """

    def __init__(self,
            name,
            # slaves for which the master is responsible
            slaves,
            elementary_cycle_length,
            # number of trigger messages to transmit per elementary cycle
            num_trigger_messages=1):
        assert isinstance(num_trigger_messages, int)
        NetworkDevice.__init__(self, name)
        self.slaves = slaves
        self.EC_length = elementary_cycle_length
        self.num_trigger_messages = num_trigger_messages
        # This counter is incremented after each successive elementary cycle
        self.EC_count = 0

    def broadcast_trigger_message(self):
        trigger_message = Message(self, self.slaves, "TM")
        trigger_message.length = Ethernet.MAX_FRAME_LENGTH
        for outlink in self.get_outlinks():
            activate(trigger_message,
                trigger_message.transmit(outlink))

    def run(self):
        while True:
            self.EC_count += 1
            time_last_EC_start = now()
            for message_count in range(self.num_trigger_messages):
                self.broadcast_trigger_message()
            # wait for the next elementary cycle to start
            while True:
                time_since_EC_start = now() - time_last_EC_start
                delay_before_next_tx_order = float(self.EC_length -
                    time_since_EC_start)
                if delay_before_next_tx_order > 0:
                    yield hold, self, delay_before_next_tx_order
                else:
                    break


class TriggerMessage(Message):
    """
    Class for trigger messages sent by the FTT masters.
    """

    def __init__(self):
        Message.__init__(self)
        self.name = "TM{:03d}".format(self.ID)


class Slave(NetworkDevice):
    """
    Class for FTT slaves.
    """

    def transmit_synchronous_messages(self,
            # number of messages to transmit
            number,
            # links on which to transmit each of the messages
            links):
        assert isinstance(number, int)
        for message_count in range(number):
            # TODO: decide who each message should be transmitted to. For now
            # we simply send it to ourselves.
            new_message = Message(self, [self], "sync")
            new_message.length = Ethernet.MAX_FRAME_LENGTH
            # order the transmission of the message on the specified links
            for outlink in links:
                activate(new_message, new_message.transmit(outlink))

    def run(self):
        while True:
            # sleep until a message is received
            yield passivate, self
            received_messages = self.read_inlinks()
            has_received_trigger_message = False
            for message in received_messages:
                if message.is_trigger_message():
                    has_received_trigger_message = True
            if has_received_trigger_message:
                # transmit on all outlinks
                self.transmit_synchronous_messages(2, self.get_outlinks())
                # wait before we order the next transmission
                delay_before_next_tx_order = 0.0
                yield hold, self, delay_before_next_tx_order