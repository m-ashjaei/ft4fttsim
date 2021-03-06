# author: David Gessner <davidges@gmail.com>

import simpy
from ft4fttsim.ethernet import Ethernet
from ft4fttsim.exceptions import FT4FTTSimException
from ft4fttsim.simlogging import log
import collections


class Port:
    """
    Instances of this class model physical Ethernet ports. Instances of the
    class NetworkDevice can have several such ports, and to each one of them an
    instance of Link can be attached.

    """

    class InputQueue(simpy.Store):

        def __init__(self, env, device):
            simpy.Store.__init__(self, env)

        def __repr__(self):
            return "{}-inQ".format(self.device)

    class OutputQueue(simpy.Store):

        def __init__(self, env, device):
            simpy.Store.__init__(self, env, capacity=1)
            self.device = device

        def __repr__(self):
            return "{}-outQ{}".format(self.device, id(self))

    def __init__(self, env, device):
        self.in_queue = Port.InputQueue(env, device)
        self.out_queue = Port.OutputQueue(env, device)
        self.device = device
        # indicates whether the port is already connected to a link
        self.is_free = True

    def __repr__(self):
        return "{}-port{}".format(self.device, id(self))


class Link:
    """
    Class whose instances model links used in an Ethernet network.

    A Link object models a physical link between at most 2 network devices
    (objects of class NetworkDevice). A Link object has a certain transmission
    speed (expressed in megabits per second) and propagation delay (expressed
    in microseconds).

    """
    def __init__(
            self, env,
            port1, port2,
            megabits_per_second, propagation_delay_us):
        """
        Create a new instance of class Link.

        Arguments:
            port1: An instance of Port that will be attached to the link
                instance.
            port2: An instance of Port that will be attached to the link
                instance.
            megabits_per_second: Speed of the link in megabits per second.
            propagation_delay_us: Propagation delay of the link in
                microseconds.

        Raises:
            FT4FTTSimException: error if the arguments have invalid values,
                e.g., a negative value for the propagation delay.

        """
        if megabits_per_second <= 0:
            raise FT4FTTSimException("Mbps must be a positive number.")
        if propagation_delay_us < 0:
            raise FT4FTTSimException("Propagation delay cannot be negative.")
        if not isinstance(port1, Port):
            raise FT4FTTSimException(
                "port1 argument must be a port and not {}.".format(
                    type(port1)))
        if not isinstance(port2, Port):
            raise FT4FTTSimException(
                "port2 argument must be a port and not {}.".format(
                    type(port2)))
        assert port1.is_free
        assert port2.is_free
        self.sublink = (
            _Sublink(env, self, port1, port2),
            _Sublink(env, self, port2, port1)
        )
        port1.is_free = False
        port2.is_free = False
        self.megabits_per_second = megabits_per_second
        self.propagation_delay_us = propagation_delay_us

    def transmission_time_us(self, num_bytes):
        """
        Return the number of microseconds that it would take a transmitter to
        transmit num_bytes on the link instance. This is the time from when the
        first bit until the last bit has left the transmitter.

        Example:

        Assuming a link of 100 Mbps, and 1526 bytes to transmit, results in a
        transmission time of 1526 * 8 / 10**8 = 122.08 microseconds:

        >>> env = simpy.Environment()
        >>> d = NetworkDevice(env, "some device", 1)
        >>> d2 = NetworkDevice(env, "another device", 1)
        >>> link = Link(env, d.ports[0], d2.ports[0], 100, 0)
        >>> link.transmission_time_us(1526)
        122.08

        """
        BITS_PER_BYTE = 8
        bits_to_transmit = num_bytes * BITS_PER_BYTE
        transmission_time_us = (bits_to_transmit / self.megabits_per_second)
        return transmission_time_us


class _Sublink:
    """
    Sublinks are directional, i.e., they have a single transmitter and a single
    receiver port. Messages that are being modeled as being transmitted can
    only be transmitted from the transmitter to the receiver port, but not in
    the opposite direction. At any one time at most one message can be
    transmitted through a sublink. If the transmission of additional messages
    is ordered through the sublink, then they will be queued.

    """
    def __init__(
            self, env, link,
            transmitter_port, receiver_port):
        """
        Create a new instance of class _Sublink.

        Arguments:
            link: the link that the sublink instance is a part of.
            transmitter_port: An instance of Port that will be attached to
                the link instance as the transmitter.
            receiver_port: An instance of Port that will be attached to
                the link instance as the receiver.

        """
        self.env = env
        self.link = link
        self._transmitter_port = transmitter_port
        self._receiver_port = receiver_port
        env.process(self.run())

    @property
    def transmitter_port(self):
        return self._transmitter_port

    @transmitter_port.setter
    def transmitter_port(self, port):
        """
        Set the port that will be transmitting through the sublink instance.

        Arguments:
            port: The port of the NetworkDevice instance to be set as the
                transmitter port for the sublink.

        """
        if self._transmitter_port is not None:
            raise FT4FTTSimException("Sublink already has a transmitter.")
        self._transmitter_port = port

    @property
    def receiver_port(self):
        return self._receiver_port

    @receiver_port.setter
    def receiver_port(self, port):
        """
        Set the port that will be receiving the traffic through the sublink
        instance.

        Arguments:
            port: The port of the NetworkDevice instance to be set as the
                receiver port for the sublink.

        """
        if self._receiver_port is not None:
            raise FT4FTTSimException("Sublink already has a receiver.")
        self._receiver_port = port

    def run(self):
        """
        Get a message from the transmitter port and simulate its transmission.

        """
        while True:
            new_message_request = self.transmitter_port.out_queue.get()
            message = yield new_message_request
            log.debug("{} transmission of {} started".format(self, message))
            # wait for the transmission + propagation time to elapse
            bytes_to_transmit = (Ethernet.PREAMBLE_SIZE_BYTES +
                                 Ethernet.SFD_SIZE_BYTES +
                                 message.size_bytes)
            yield self.env.timeout(
                self.link.transmission_time_us(bytes_to_transmit) +
                self.link.propagation_delay_us)
            log.debug("{} transmission of {} finished".format(self, message))
            self.receiver_port.in_queue.put(message)
            # wait for the duration of the ethernet interframe gap to elapse
            yield self.env.timeout(
                self.link.transmission_time_us(Ethernet.IFG_SIZE_BYTES))
            log.debug("{} inter frame gap finished".format(self))

    def __repr__(self):
        return "{}->{}".format(self._transmitter_port, self._receiver_port)

    def __str__(self):
        return "{}->{}".format(self._transmitter_port, self._receiver_port)


class NetworkDevice:

    def __init__(self, env, name, num_ports):
        self.env = env
        self.ports = [Port(self.env, self)
                      for i in range(num_ports)]
        self.name = name

    def listen_for_messages(self, callback):
        """
        Wait for the reception of messages on all ports and, once messages are
        received, invoke the callback function passing the received messages as
        a parameter.

        """
        # generate get requests for all input queues
        requests = [port.in_queue.get() for port in self.ports]
        while requests:
            # helper variable for the asserts
            queues_with_pending_requests = [req.resource for req in requests]
            # There is a request for each input queue.
            assert set(self.input_queues) == set(queues_with_pending_requests)
            # For each input queue there's exactly one request.
            assert (
                len(queues_with_pending_requests) ==
                len(set(queues_with_pending_requests)))

            log.debug("{} waiting for next reception".format(self))
            completed_requests = (yield self.env.any_of(requests))
            received_messages = list(completed_requests.values())
            log.debug("{} received {}".format(
                self, received_messages))

            callback(received_messages)

            # Only leave the requests which have not been completed yet
            remaining_requests = [
                req for req in requests if req not in completed_requests]
            # Input queues that have been emptied since the last wake up.
            emptied_queues = [req.resource for req in completed_requests]
            # Add new get requests for the input queues that have been emptied.
            new_requests = []
            for input_queue in emptied_queues:
                new_requests.append(input_queue.get())
            requests = remaining_requests + new_requests

    def instruct_transmission(self, message, port):
        """
        Note that this is a generator function. It should not be called
        directly, but only as a parameter to the process() method of a simpy
        Environment instance.

        Example:

        >>> env = simpy.Environment()
        >>> d = NetworkDevice(env, "some device", 1)
        >>> d2 = NetworkDevice(env, "another device", 1)
        >>> L = Link(env, d.ports[0], d2.ports[0], 100, 3)
        >>> m = Message(env, d, d2, 1234, "some message")
        >>> env.process(d.instruct_transmission(m, d.ports[0]))
        <Process(instruct_transmission) object at 0x...>

        """
        log.debug("{} instructing transmission of {} on {}".format(
            self, message, port))
        if port not in self.ports:
            raise FT4FTTSimException("{} is not a port of {}".format(
                port, self))
        log.debug("{} queued for transmission".format(message))
        yield port.out_queue.put(message)

    @property
    def input_queues(self):
        return [port.in_queue for port in self.ports]

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


class EchoDevice(NetworkDevice):

    def __init__(self, env, name):
        NetworkDevice.__init__(self, env, name, 1)
        self.env.process(self.listen_for_messages(self.echo))

    def echo(self, messages):
        for m in messages:
            self.env.process(self.instruct_transmission(m, self.ports[0]))


class MessageRecordingDevice(NetworkDevice):
    """
    Class whose instances model a passive receiver.

    Instances of this class cannot transmit messages. All they do is wait for
    the reception of a message on any one of their ports and record the
    received message in an internal buffer together with a timestamp of the
    reception time.

    The main purpose of instances of this class is to make testing easier.

    """

    def __init__(self, env, name, num_ports):
        NetworkDevice.__init__(self, env, name, num_ports)
        self.reception_records = {}
        self.env.process(self.listen_for_messages(self.do_timestamp_messages))

    def do_timestamp_messages(self, messages):
        timestamp = self.env.now
        self.reception_records[timestamp] = messages
        log.debug("{} recorded {}".format(self, self.reception_records))

    @property
    def recorded_messages(self):
        messages = []
        for time in sorted(self.reception_records):
            messages.extend(self.reception_records[time])
        return messages

    @property
    def recorded_timestamps(self):
        return sorted(self.reception_records.keys())


class MessagePlaybackDevice(NetworkDevice):
    """
    Instances of this class model devices that transmit prespecified messages.

    Instances of this class cannot receive messages. What they do is accept a
    series of transmission commands and then execute them. Each transmission
    command specifies what message to transmit at what time and through which
    port.

    The main purpose of instances of this class is to make testing easier.

    """

    def __init__(self, env, name, num_ports):
        NetworkDevice.__init__(self, env, name, num_ports)
        env.process(self.run())
        self.transmission_commands = {}

    def load_transmission_commands(self, transmission_commands):
        """
        Load the transmission commands to execute once the run method is
        activated by simpy.

        Arguments:
            transmission_commands: The transmission commands to execute once
                the run method is activated by the simulator. This argument
                should be a dictionary whose keys are instants of time when
                message transmissions should be instructed. Each of the values
                of the dictionary should be another dictionary whose keys are
                the ports on which transmissions should be ordered and
                whose values are lists of messages to be transmitted through
                the corresponding port. Example:

                {
                    0.0:  {port1: [message1, message2]},
                    12.0: {port1: [message3]},
                    13.5: {port3: [message4, message5, message6]}
                }

        """
        self.transmission_commands = transmission_commands
        log.debug("{} loaded transmissions: {}".format(
            self, self.transmission_commands))

    def run(self):
        for time in sorted(self.transmission_commands):
            delay_before_next_tx_order = time - self.env.now
            log.debug("{} waiting for next transmission time".format(self))
            # wait until next transmission time
            yield self.env.timeout(delay_before_next_tx_order)
            for port, messages_to_tx in \
                    self.transmission_commands[time].items():
                for message in messages_to_tx:
                    self.env.process(
                        self.instruct_transmission(message, port))

    @property
    def transmission_start_times(self):
        return sorted(self.transmission_commands.keys())


class MessagePlaybackAndRecordingDevice(
        MessagePlaybackDevice, MessageRecordingDevice):

    def __init__(self, env, name, num_ports):
        MessagePlaybackDevice.__init__(self, env, name, num_ports)
        self.reception_records = {}
        self.env.process(self.listen_for_messages(self.do_timestamp_messages))


class Switch(NetworkDevice):
    """
    Class whose instances model Ethernet switches.

    """

    def __init__(self, env, name, num_ports, forwarding_table={}):
        NetworkDevice.__init__(self, env, name, num_ports)
        env.process(self.listen_for_messages(self.forward_messages))
        # Dictionary whose keys are network devices and whose values are ports
        # of the Switch instance.
        self.forwarding_table = forwarding_table

    def forward_messages(self, message_list):
        """
        Forward each message in 'message_list' through the appropriate port.

        Note that forwarding a message from one port to another port is
        implemented as creating a new message instance based on the message
        in the first port, and transmitting the new message instance on the
        second port.
        """

        def find_ports(destination):
            """
            Return a list of the ports that according to the forwarding table
            lead to 'destination'.

            Arguments:
                destination: an instance of class NetworkDevice or an iterable
                    of NetworkDevice instances.

            Returns:
                A set of the ports that lead to the devices in 'destination'.

            """
            output_ports = set()
            if isinstance(destination, collections.Iterable):
                for device in destination:
                    # ports leading to device
                    ports_towards_device = self.forwarding_table.get(
                        device, self.ports)
                    output_ports.update(ports_towards_device)
            else:
                output_ports.update(
                    self.forwarding_table.get(destination, self.ports))
            return output_ports

        for message in message_list:
            destinations = message.destination
            output_ports = find_ports(destinations)
            for port in output_ports:
                new_message = Message.from_message(message)
                self.env.process(
                    self.instruct_transmission(new_message, port))


class Message:
    """
    Class for messages that model Ethernet frames.

    """
    # next available ID for message objects
    next_ID = 0

    def __init__(self, env, source, destination, size_bytes, message_type):
        """
        Create an instance of Message.

        Arguments:
            source: usually an instance of NetworkDevice. It models the
                MAC source address field of an Ethernet frame.
            destination: usually an instance of NetworkDevice or a list of
                instances of NetworkDevice. It models the MAC destination
                address field of an Ethernet frame. If it is iterable, then it
                models a multicast address, otherwise it models a unicast
                address.
            size_bytes: indicates the size in bytes of the Ethernet frame
                modeled by the Message instance created. The size does not
                include the Ethernet preamble, the start of frame delimiter, or
                an IEEE 802.1Q tag.
            message_type: models the Ethertype field.

        """
        if not isinstance(size_bytes, int):
            raise FT4FTTSimException("Message size must be integer")
        if not (Ethernet.MIN_FRAME_SIZE_BYTES <= size_bytes <=
                Ethernet.MAX_FRAME_SIZE_BYTES):
            raise FT4FTTSimException(
                "Message size must be between {} and {}, but is {}".format(
                Ethernet.MIN_FRAME_SIZE_BYTES, Ethernet.MAX_FRAME_SIZE_BYTES,
                size_bytes))
        self.env = env
        self.ID = Message.next_ID
        Message.next_ID += 1
        # source of the message. Models the source MAC address.
        self.source = source
        # destination of the message. It models the destination MAC address. It
        # is a list to allow multicast addressing.
        self.destination = destination
        self.size_bytes = size_bytes
        self.message_type = message_type
        self.name = "({:03d}, {}, {}, {:d}, {})".format(
            self.ID, self.source, self.destination, self.size_bytes,
            self.message_type)
        log.debug("{} created".format(self))

    @classmethod
    def from_message(cls, template_message):
        """
        Creates a new message instance using template_message as a template.

        """
        new_equivalent_message = cls(
            template_message.env,
            template_message.source,
            template_message.destination,
            template_message.size_bytes,
            template_message.message_type)
        return new_equivalent_message

    def __eq__(self, message):
        """
        Returns true if self and message are identical except for the message
        ID.

        """
        return (self.source == message.source and
                self.destination == message.destination and
                self.size_bytes == message.size_bytes and
                self.message_type == message.message_type)

    def is_trigger_message(self):
        return self.message_type == "TM"

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name
