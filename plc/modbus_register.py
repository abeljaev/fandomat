import threading

class ModbusRegister:
    def __init__(self, slave, register_number):
        self.lock = threading.Lock()
        self.slave = slave
        self.register_number = register_number
        self.value = 0x0000

    def set_bit(self, bit_num, state):
        with self.lock:
            if state:
                self.value |= (1 << bit_num)
            else:
                self.value &= ~(1 << bit_num)
            self.sync_to_device()

    def get_bit(self, bit_num):
        with self.lock:
            return (self.value >> bit_num) & 1

    
    def set_value(self, value):
        with self.lock:
            self.value = value
            self.sync_to_device()

    def get_value(self):
        with self.lock:
            return self.value

    def reset_all_bits(self):
        with self.lock:
            self.value = 0x0000
            self.sync_to_device()

    def sync_to_device(self):         
        self.slave.set_values('holding', self.register_number, self.value)

    def sync_from_device(self):
        status = self.slave.get_values('holding', self.register_number, 1)
        if status:
            with self.lock:
                self.value = status[0]