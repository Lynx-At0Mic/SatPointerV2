import RPi.GPIO as io
from RPLCD.i2c import CharLCD
from smbus2 import SMBus
from pyorbital.orbital import Orbital
import configparser
from datetime import datetime as datet
from time import sleep

config = configparser.ConfigParser()
config.read("config.txt")

# Setup i2c
i2c = SMBus(1)
arduinoAddress = 0x08

# Setup LCD
lcd = CharLCD('PCF8574', 0x3f, port=1, cols=20, rows=4)

# Setup GPIO
clk = int(config["GPIO"]["CLK"])
dt = int(config["GPIO"]["DT"])
sw = int(config["GPIO"]["SW"])

io.setmode(io.BCM)  # initialise GPIO
io.setup(clk, io.IN, pull_up_down=io.PUD_UP)
io.setup(dt, io.IN, pull_up_down=io.PUD_UP)
io.setup(sw, io.IN, pull_up_down=io.PUD_UP)

# Globals
exitFlag = False

el = 0.0  # Satellite elevation in degrees
az = 0.0  # Satellite azimuth in degrees

sat_list = config["TLE"]["WHITELIST"].split("\n")
satelliteName = sat_list[0]  # Satellite name
curSatellite = ""
sat_object = None

lat = float(config["GROUND STATION"]["LAT"])  # position of device
lng = float(config["GROUND STATION"]["LONG"])
alt = float(config["GROUND STATION"]["ALT"])

dateandtime = datet(2020, 1, 1, 0, 0, 0)  # initilise time variable

degtostep = int(config["MOTION"]["STEPS PER REVOLUTION"]) / 360


# LCD menu class
class LCDmenu():
    def __init__(self, items, clk, dt):
        self._items = items
        self._activeIndex = 0
        self._maxindex = len(self._items) - 1
        self._page = 0

        self._clk = clk
        self._dt = dt
        self._clklaststate = io.input(self._clk)
        self._clkcounter = 0

        io.add_event_detect(self._clk, io.FALLING, callback=self._encoder_callback)

    def disable(self):
        lcd.clear()
        io.remove_event_detect(self._clk)

    def enable(self):
        lcd.clear()
        self.display()
        self.cursor()
        io.add_event_detect(self._clk, io.FALLING, callback=self._encoder_callback)

    def display(self):
        lcd.clear()
        lcd.home()
        for i in range((self._page*4), (self._page*4)+4):
            if i > self._maxindex:
                break
            lcd.write_string(str(self._items[i]))
            lcd.crlf()

    def increment_index(self):
        if self._activeIndex != self._maxindex:
            self._set_index(self._activeIndex + 1)

    def decrement_index(self):
        if self._activeIndex != 0:
            self._set_index(self._activeIndex - 1)

    def _set_index(self, index):
        self._activeIndex = index
        self.cursor()

    def get_index(self):
        return self._activeIndex

    def cursor(self):
        screenIndex = self._activeIndex - self._page*4

        while screenIndex < 0:
            screenIndex += 4
            self._page -= 1
            self.display()

        while screenIndex > 3:
            screenIndex -= 4
            self._page += 1
            self.display()

        for i in range(0,4):
            lcd.cursor_pos = i, 19
            lcd.write_string(" ")
        lcd.cursor_pos = screenIndex, 19
        lcd.write_string("<")

    def _encoder_callback(self, callback):
        io.remove_event_detect(self._clk)  # remove event temporarily to stop duplicate triggers

        dtstate = io.input(self._dt)  # get state of dt

        if dtstate == 1:  # clk is 0 due to trigger, if dt is 1 it turned right is its 0 it turned left
            self.increment_index()
        elif dtstate == 0:
            self.decrement_index()

        io.add_event_detect(self._clk, io.FALLING, callback=self._encoder_callback)  # add event back


def get_az_el():
    global az, el, curSatellite, sat_object, satelliteName

    if satelliteName == "None":  # set everything to 0 if nothing is selected to track
        az, el = 0, -90
        return

    if curSatellite != satelliteName:
        try:
            sat_object = Orbital(satelliteName, tle_file=str(config["TLE"]["PATH"]))
        except:
            lcd.clear()
            lcd.write_string("SAT NOT IN TLE")
            satelliteName = "None"
            sleep(3)
            return
        
        curSatellite = satelliteName
        
    az, el = sat_object.get_observer_look(dateandtime, lng, lat, alt)


def send_data(pass_az, pass_el):
    value1 = int(pass_az * degtostep)  # turn azimuth into steps
    value2 = int(pass_el + int(config["MOTION"]["SERVO OFFSET"]))

    if value1 > 65535:  # return if value > 2 bytes to avoid errors
        return

    bin_value1 = bin(value1)  # convert value to binary
    bin_value1 = bin_value1[2:]  # drop sign bits

    while len(bin_value1) < 16:
        bin_value1 = "0" + bin_value1  # add zeros to make 16 bits

    byte1 = int(bin_value1[:8], 2)  # store first byte
    byte2 = int(bin_value1[8:], 2)  # store second byte

    data = [byte1, byte2, value2]  # put data together

    i2c.write_block_data(arduinoAddress, 0, data)  # send data over i2c to arduino


def display():
    lcd.clear()
    lcd.write_string("Tracking:")
    lcd.crlf()
    lcd.write_string(satelliteName)
    lcd.crlf()
    lcd.write_string("AZ: {} EL: {}".format(round(az, 1), round(el, 1)))
    lcd.crlf()


options_items = ["Back", "Change Target", "Quit"]


def options():
    lcd.clear()
    options_menu = LCDmenu(options_items, clk, dt)
    options_menu.display()
    options_menu.cursor()

    io.wait_for_edge(sw, io.FALLING)

    sel_index = options_menu.get_index()

    if sel_index == 0:
        options_menu.disable()
        return
    elif sel_index == 1:
        options_menu.disable()
        tracking_select()
    else:
        global exitFlag
        exitFlag = True


def tracking_select():
    global satelliteName

    tracking_menu = LCDmenu(sat_list, clk, dt)
    tracking_menu.display()
    tracking_menu.cursor()

    io.wait_for_edge(sw, io.FALLING)

    satelliteName = sat_list[tracking_menu.get_index()]

    tracking_menu.disable()
    

def update_tle():
    print()


try:
    while not exitFlag:
        dateandtime = datet.utcnow()
        get_az_el()
        send_data(az, el)
        display()
        user_event = io.wait_for_edge(sw, io.FALLING, timeout=2500)
        if user_event is not None:
            options()


finally:
    lcd.clear()
    lcd.write_string("Exiting...")
    sleep(1.5)
    lcd.clear()
    io.cleanup()
