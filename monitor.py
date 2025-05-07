#!/usr/bin/python3
import json
import logging
import time
import os
import threading
import adafruit_ssd1306
from PIL import ImageFont, Image, ImageDraw
from netifaces import interfaces, ifaddresses, AF_INET
from board import SCL, SDA
import adafruit_ssd1306
import busio
import sys
import argparse

STATS1090 = "/usr/share/graphs1090/data-symlink/data/status.json"
STATS978 = "/usr/share/graphs1090/978-symlink/data/status.json"
DETAILSTATS = "/usr/share/graphs1090/data-symlink/data/stats.json"
WLANFILE = "/home/pi/wpa_supp.default"
WLANTARGET = "/etc/wpa_supplicant/wpa_supplicant.conf"
TRACKER_STATS_FILE = "tracker_stats.json"

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.debug("Logging is set up.")

font = False
booted = False
resetlock = threading.Lock()
displaylock = threading.Lock()

def get_aircraft_stats(fn):
    try:
        with open(fn) as fd:
            json_result = json.load(fd)
            return json_result['aircraft_with_pos']
    except Exception:
        return "xxx"

def getrssi():
    try:
        with open(DETAILSTATS) as fd:
            json_result = json.load(fd)
            peak = json_result['last1min']['local']['peak_signal']
    except Exception:
        peak = "None"
    return peak

def getwlanip():
    return [i['addr'] for i in ifaddresses("wlan0").setdefault(AF_INET, [{'addr':'No IP addr'}] )][0]

def screensetup():
    global font

    time.sleep(1)
    print("starting screen setup")

    i2c = busio.I2C(SCL, SDA)
    dispobj = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c)
    time.sleep(1)

    # Clear display.
    dispobj.fill(0)
    dispobj.show()

    font = ImageFont.load_default(size=11)
    width = dispobj.width
    height = dispobj.height
    imageobj = Image.new('1', (width, height))

    # Get drawing object to draw on image.
    drawobj = ImageDraw.Draw(imageobj)
    return drawobj, imageobj, dispobj

def clearscreen(drawobj):
    if drawobj: drawobj.rectangle((0,0,128,64), outline=0, fill=0)

def writeline(drawobj, linenum, text):
    if drawobj:
        drawobj.text((4, -2+(linenum*9)), text, font=font, fill=255)
#    print(text)

def showtext(dispobj, imageobj):
    if dispobj:
        dispobj.image(imageobj)
        dispobj.show()

def gettemp():
    fn = "/sys/class/thermal/thermal_zone0/temp"
    with open(fn) as f:
        firstline = f.readline().rstrip()
    return int(firstline)/1000

def write_adsb_data(drawobj):
    writestr = f"1090 aircraft: {get_aircraft_stats(STATS1090)}"
    writeline(drawobj, 2, writestr)

    writestr = f"978 aircraft: {get_aircraft_stats(STATS978)}"
    writeline(drawobj, 3, writestr)

    writestr = f"Peak RSSI: {getrssi()}"
    writeline(drawobj, 4, writestr)

def write_mesh_data(drawobj, fn):
    from tracker_stats import TrackerQueue

    tq = TrackerQueue(100)
    tq.load_from_file(fn)

    # print the last 6 entries in order, three per line, two lines
    entries = [tq.format_nth_entry(i) for i in range(6)]
    logger.debug("writing to screen: " + str(entries))
    for line_num in range(2):
        writestr = " - ".join(entries[line_num * 3:(line_num + 1) * 3])
        writeline(drawobj, 2 + line_num, writestr)

def write_sysstat(drawobj):
    # get the disk iowait, cpu load, and memory pressure
    try:
        # CPU stats
        with open("/proc/stat") as fd:
            lines = fd.readlines()
            cpu_line_1 = lines[0].split()
            time.sleep(1)  # Wait for 1 second to calculate recent stats
            fd.seek(0)
            lines = fd.readlines()
            cpu_line_2 = lines[0].split()

            cpu_diff = [int(cpu_line_2[i]) - int(cpu_line_1[i]) for i in range(1, len(cpu_line_1))]
            total_diff = sum(cpu_diff)
            idle_diff = cpu_diff[3]  # idle time is the 4th column

            cpu_load = 100 - (idle_diff / total_diff) * 100
            iowait = (cpu_diff[4] / total_diff) * 100  # iowait is the 5th column

        # Memory stats
        with open("/proc/meminfo") as fd:
            meminfo = {}
            for line in fd:
                key, value = line.split(":")
                meminfo[key.strip()] = int(value.split()[0])  # Value is in kB

            total_memory = meminfo["MemTotal"]
            free_memory = meminfo["MemFree"]
            cached_memory = meminfo["Cached"]
            available_memory = free_memory + cached_memory

            available_memory_pct = (available_memory / total_memory) * 100
    except Exception:
        cpu_load = "None"
        iowait = "None"
        available_memory_pct = "None"

    writeline(drawobj, 2, f"CPU load: {cpu_load:.1f}%")
    writeline(drawobj, 3, f"IOwait: {iowait:.1f}%")
    writeline(drawobj, 4, f"Avail memory: {available_memory_pct:.1f}%")

if __name__ == "__main__":
    # Parse command line arguments for --mode
    parser = argparse.ArgumentParser(description="Monitor script for OLED display.")
    parser.add_argument("--detail", choices=["adsb", "mesh", "sysstat"], default="sysstat",
                        help="Set detail information to show. Options: 'adsb', 'mesh'.")
    parser.add_argument("--file", type=str, default=TRACKER_STATS_FILE)
    args = parser.parse_args()

    draw, image, disp = screensetup()
    clearscreen(draw)
    writeline(draw, 0, "Booting...")
    showtext(disp, image)

    booted = True
    spinarr="|/-\\|/-\\"
    spinoff=0
    temp = gettemp()

    while True:
        with displaylock:
            clearscreen(draw)

            writeline(draw, 0, f"IP: {getwlanip()}")

            if args.detail == "adsb":
                write_adsb_data(draw)
            elif args.detail == "mesh":
                write_mesh_data(draw, args.file)
            elif args.detail == "sysstat":
                write_sysstat(draw)
            else:
                writeline(draw, 1, "No detail mode selected")

            if spinoff == len(spinarr):
                spinoff = 0
                temp = gettemp()
            writestr = f"Temp: {temp:.1f}    {spinarr[spinoff]}"
            spinoff += 1
            writeline(draw, 6, writestr)
            showtext(disp, image)

        time.sleep(1)
