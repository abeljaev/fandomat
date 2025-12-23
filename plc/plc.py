from plc.modbus_register import ModbusRegister
import modbus_tk.defines as cst
import serial
from modbus_tk import modbus_rtu
import logging
import threading

logging.getLogger('modbus_tk').setLevel(logging.CRITICAL)

class PLC:
    def __init__(self, serial_port, baudrate, slave_address, cmd_register = 25, status_register = 26, speed = 500):
        self.serial_port = serial_port
        self.baudrate = baudrate

        self.cmd_register = cmd_register
        self.status_register = status_register
        
        self.ser = serial.Serial(
                port = self.serial_port,
                baudrate = self.baudrate,
                bytesize = 8,
                parity = 'N',
                stopbits = 1,
                xonxoff = 0
        )

        self.server = modbus_rtu.RtuServer(self.ser)
        self.slave = self.server.add_slave(slave_address)
        self.server.start()

        self.modbus_register_cmd = ModbusRegister(self.slave, self.cmd_register)
        self.modbus_register_status = ModbusRegister(self.slave, self.status_register)
        self.modbus_register_speed = ModbusRegister(self.slave, 24)
        # self.modbus_register_counter = ModbusRegister(self.slave, 25)

        # Счетчики и проценты заполнения
        self.modbus_register_bank_counter = ModbusRegister(self.slave, 20)
        self.modbus_register_bottle_counter = ModbusRegister(self.slave, 21)
        self.modbus_register_bottle_percent = ModbusRegister(self.slave, 22)
        self.modbus_register_bank_percent = ModbusRegister(self.slave, 23)

        self.slave.add_block('holding', cst.HOLDING_REGISTERS, 10, 17)
        self.modbus_register_speed.set_value(speed)

        # Lock для потокобезопасного доступа к Modbus
        self._modbus_lock = threading.Lock()

    def stop(self):
        self.server.stop()
        self.ser.close()

    def update_data(self):
        """Синхронизировать данные с устройства (потокобезопасно)."""
        with self._modbus_lock:
            self.modbus_register_status.sync_from_device()
            # self.modbus_register_counter.sync_from_device()
            self.modbus_register_bank_counter.sync_from_device()
            self.modbus_register_bottle_counter.sync_from_device()
            self.modbus_register_bottle_percent.sync_from_device()
            self.modbus_register_bank_percent.sync_from_device()

    # Команды на получение статуса (регистр 26)
    def get_state_veil(self):
        return self.modbus_register_status.get_bit(0)
    
    def get_state_left_sensor_carriage(self):
        return self.modbus_register_status.get_bit(1)
    
    def get_state_center_sensor_carriage(self):
        return self.modbus_register_status.get_bit(2)
    
    def get_state_right_sensor_carriage(self):
        return self.modbus_register_status.get_bit(3)
    
    def get_state_unknown_sensor_carriage(self):
        return self.modbus_register_status.get_bit(4)
    
    def get_state_weight_error(self):
        return self.modbus_register_status.get_bit(5)
    
    def get_bank_exist(self):
        return self.modbus_register_status.get_bit(6)
    
    def get_bottle_exist(self):
        return self.modbus_register_status.get_bit(7)
    
    def get_weight_too_small(self):
        return self.modbus_register_status.get_bit(8)

    def get_bottle_weight_ok(self):
        return self.modbus_register_status.get_bit(9)
    
    def get_bank_weight_ok(self):
        return self.modbus_register_status.get_bit(10)
    
    def get_status_work(self):
        return self.modbus_register_status.get_bit(11)
    
    def get_left_movement_error(self):
        return self.modbus_register_status.get_bit(12)
    
    def get_right_movement_error(self):
        return self.modbus_register_status.get_bit(13)

    # Счетчики и проценты заполнения (регистры 20-23)
    def get_bank_count(self) -> int:
        """Получить общее количество банок (регистр 20)."""
        return self.modbus_register_bank_counter.get_value()

    def get_bottle_count(self) -> int:
        """Получить общее количество бутылок (регистр 21)."""
        return self.modbus_register_bottle_counter.get_value()

    def get_bottle_fill_percent(self) -> int:
        """Получить процент заполнения мешка бутылок (регистр 22)."""
        return self.modbus_register_bottle_percent.get_value()

    def get_bank_fill_percent(self) -> int:
        """Получить процент заполнения мешка банок (регистр 23)."""
        return self.modbus_register_bank_percent.get_value()

    # Команды на отправку команд (регистр 25) - потокобезопасные
    def cmd_lock_and_block_carriage(self):
        with self._modbus_lock:
            self.modbus_register_cmd.set_bit(0, 1)

    def cmd_weight_error_reset(self):
        with self._modbus_lock:
            self.modbus_register_cmd.set_bit(1, 1)

    def cmd_reset_bank_counters(self):
        with self._modbus_lock:
            self.modbus_register_cmd.set_bit(2, 1)

    def cmd_reset_bottle_counters(self):
        with self._modbus_lock:
            self.modbus_register_cmd.set_bit(3, 1)

    def cmd_force_move_carriage_left(self):
        with self._modbus_lock:
            self.modbus_register_cmd.set_bit(4, 1)

    def cmd_force_move_carriage_right(self):
        with self._modbus_lock:
            self.modbus_register_cmd.set_bit(5, 1)

    def cmd_radxa_detected_bank(self):
        with self._modbus_lock:
            self.modbus_register_cmd.set_bit(6, 1)

    def cmd_radxa_detected_bottle(self):
        with self._modbus_lock:
            self.modbus_register_cmd.set_bit(7, 1)

    def cmd_radxa_stop_detected_bank(self):
        with self._modbus_lock:
            self.modbus_register_cmd.set_bit(6, 0)

    def cmd_radxa_stop_detected_bottle(self):
        with self._modbus_lock:
            self.modbus_register_cmd.set_bit(7, 0)

    def cmd_reset_weight_reading(self):
        with self._modbus_lock:
            self.modbus_register_cmd.set_bit(8, 1)

    def cmd_full_clear_register(self):
        with self._modbus_lock:
            self.modbus_register_cmd.reset_all_bits()
