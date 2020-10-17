import binascii
import collections
import os
import socket
import struct
import sys
import time

import serial

BAUDRATE = 115200

CHAR_WIDTH = 12
CHAR_HEIGHT = 18

def grid_size_to_pixels(gw, gh):
    return (gw * CHAR_WIDTH, gh * CHAR_HEIGHT)

# For initial bootloader version, just cosmetic
_ALLOW_WORKAROUND = True

class CMD:
    ERROR = 0

    INFO = 1
    READ_FONT = 2
    WRITE_FONT = 3

    GET_ACTIVE_CAMERA = 6

    TRANSACTION_BEGIN = 16
    TRANSACTION_COMMIT = 17
    TRANSACTION_BEGIN_PROFILED = 18

    SET_STROKE_COLOR = 22
    SET_FILL_COLOR = 23
    SET_STROKE_AND_FILL_COLOR = 24
    SET_COLOR_INVERSION = 25
    SET_PIXEL = 26
    SET_PIXEL_TO_STROKE_COLOR = 27
    SET_PIXEL_TO_FILL_COLOR = 28
    SET_STROKE_WIDTH = 29
    SET_LINE_OUTLINE_TYPE = 30
    SET_LINE_OUTLINE_COLOR = 31

    CLIP_TO_RECT = 40
    CLEAR_SCREEN = 41
    CLEAR_RECT = 42
    DRAWING_RESET = 43
    DRAW_BITMAP = 44
    DRAW_BITMAP_MASK = 45
    DRAW_CHAR = 46
    DRAW_CHAR_MASK = 47
    DRAW_STRING = 48
    DRAW_STRING_MASK = 49
    MOVE_TO_POINT = 50
    STROKE_LINE_TO_POINT = 51
    STROKE_TRIANGLE = 52
    FILL_TRIANGLE = 53
    FILL_STROKE_TRIANGLE = 54
    STROKE_RECT = 55
    FILL_RECT = 56
    FILL_STROKE_RECT = 57
    STROKE_ELLIPSE_IN_RECT = 58
    FILL_ELLIPSE_IN_RECT = 59
    FILL_STROKE_ELLIPSE_IN_RECT = 60

    CTM_RESET = 80
    CTM_SET = 81
    CTM_TRANSLATE = 82
    CTM_SCALE = 83
    CTM_ROTATE = 84
    CTM_ROTATE_ABOUT = 85
    CTM_SHEAR = 86
    CTM_SHEAR_ABOUT = 87
    CTM_MULTIPLY = 88
    CTM_TRANSLATE_REV = 89

    CONTEXT_PUSH = 100
    CONTEXT_POP = 101

    DRAW_GRID_CHR = 110
    DRAW_GRID_STR = 111
    DRAW_GRID_CHR_2 = 112               # API2
    DRAW_GRID_STR_2 = 113               # API2

    WIDGET_SET_CONFIG = 115             # API2
    WIDGET_DRAW = 116                   # API2
    WIDGET_ERASE = 117                  # API2

    REBOOT = 120
    WRITE_FLASH = 121
    SET_DATA_RATE = 122

    VM_STORAGE_SIZE = 150               # API2
    VM_STORAGE_READ = 151               # API2
    VM_STORAGE_WRITE = 152              # API2
    VM_START = 153                      # API2
    VM_LOOKUP_SYMBOL = 154              # API2
    VM_EXEC = 155                       # API2

class COLOR:
    BLACK = 0
    TRANSPARENT = 1
    WHITE = 2
    GRAY = 3

    _MIN = BLACK
    _MAX = GRAY

class OUTLINE:
    NONE = 0
    TOP = 1 << 0
    RIGHT = 1 << 1
    BOTTOM = 1 << 2
    LEFT = 1 << 3

class BITMAP_OPTS:
    INVERSE = 1 << 0
    SOLID_BG = 1 << 1
    ERASE_TRANSPARENT = 1 << 2

class WIDGETS:
    AHI = 0
    AHI_STYLE_STAIRCASE = 0
    AHI_STYLE_LINE = 1
    AHI_OPTION_SHOW_CORNERS = 1 << 0

    SIDEBAR_0 = 1
    SIDEBAR_1 = 2
    SIDEBAR_OPTION_LEFT = 1 << 0
    SIDEBAR_OPTION_REVERSE = 1 << 1
    SIDEBAR_OPTION_UNLABELED = 1 << 2
    SIDEBAR_OPTION_STATIC = 1 << 3

    GRAPH_0 = 3
    GRAPH_1 = 4
    GRAPH_2 = 5
    GRAPH_3 = 6

    GRAPH_OPTION_BATCHED = 1 << 0

    CHARGAUGE_0 = 7
    CHARGAUGE_1 = 8
    CHARGAUGE_2 = 9
    CHARGAUGE_3 = 10


FLASH_WRITE_MAX_BLOCK_SIZE = 64
FLASH_WRITE_END = (2 << 31) - 1

MAX_SEND_BUFFER_SIZE = 254

def _int_as_bytes(i):
    return struct.pack('B', i)

def _bytes_as_ints(b):
    values = []
    while len(b) > 0:
        values.append(struct.unpack('B', b[:1])[0])
        b = b[1:]
    return values

def _bytes_have_prefix(b, prefix):
    for ii, v in enumerate(prefix):
        bb = b[ii]
        if isinstance(bb, str):
            # Python 2
            bb = ord(bb)
        if bb != ord(v):
            return False
    return True

def _str_to_bytes(s):
    if bytes is str:
        # Python 2
        return s
    # Python 3
    return bytes(s, 'ascii')

def _format_payload(p):
    values = None
    if isinstance(p, bytearray):
        values = p
    elif isinstance(p, str):
        values = [struct.unpack('B', v)[0] for v in p]
    elif isinstance(p, bytes):
        values = p
    if values:
        return ''.join(['{:02x}'.format(v) for v in values])
    return str(p)

class Unit(object):
    def __init__(self, scale, symbol, divisor, divided_symbol):
        self.scale = scale
        self.symbol = symbol
        self.divisor = divisor
        self.divided_symbol = divided_symbol

class Response(object):
    def __init__(self, cmd, payload):
        self.cmd = cmd
        self.payload = payload

    def __str__(self):
        return 'CMD = {}, {}'.format(self.cmd, self._payload_str())

    def _payload_str(self):
        return '{} bytes = {}'.format(len(self.payload), _format_payload(self.payload))

    def byte_at(self, idx):
        return _bytes_as_ints(self.payload)[idx]

    @classmethod
    def decode(cls, cmd, payload):
        rcls = _response_cls.get(cmd)
        if rcls:
            return rcls(cmd, payload)
        return cls(cmd, payload)

class ResponseError(Response):
    def __init__(self, cmd, payload):
        super(ResponseError, self).__init__(cmd, payload)
        self.request_cmd, self.error_code = struct.unpack('<Bb', payload)

    def _payload_str(self):
        return 'in response to {}, code {}'.format(self.request_cmd, self.error_code)

class ResponseInfo(Response):
    def __init__(self, cmd, payload):
        super(ResponseInfo, self).__init__(cmd, payload)
        if _bytes_have_prefix(payload, 'AGH'):
            self.is_bootloader = False
            values = (struct.unpack('<BBBBBHHBBHB', payload[3:]))
        elif len(payload) == 1 and _bytes_have_prefix(payload, 'B'):
            self.is_bootloader = True
            values = [0] * 11
        else:
            raise RuntimeError("Invalid info prefix {0}".format(payload))

        self.major, self.minor, self.patch, self.gridRows, self.gridColumns, \
            self.pixelWidth, self.pixelHeight, self.tvStandard, \
            self.hasDetectedCamera, self.maxFrameSize, \
            self.contextStackSize = values

    @property
    def gridWidth(self):
        return self.pixelWidth / self.gridColumns

    @property
    def gridHeight(self):
        return self.pixelHeight / self.gridRows

    @property
    def version(self):
        return (self.major, self.minor, self.patch)

class ResponseWriteFlash(Response):
    def __init__(self, cmd, payload):
        super(ResponseWriteFlash, self).__init__(cmd, payload)
        self.addr = struct.unpack('<L', payload)[0]

    def _payload_str(self):
        return '{:#08x}'.format(self.addr)

_response_cls = {
    CMD.ERROR: ResponseError,
    CMD.INFO: ResponseInfo,
    CMD.WRITE_FLASH: ResponseWriteFlash,
}

class RemoteResponseError(Exception):
    """Raised when the OSD returns an error over the protocol"""
    def __init__(self, resp, message=None):
        message = message or resp.__str__()
        super(RemoteResponseError, self).__init__(message)
        self.resp = resp
        self.message = message

class SerialConn:
    def __init__(self, port, baudrate):
        self._conn = serial.Serial(port, baudrate)

    def write(self, b):
        return self._conn.write(b)

    def read(self):
        return self._conn.read()

    def close(self):
        return self._conn.close()

    @classmethod
    def accepts(cls, port):
        if port.lower().startswith('COM'):
            # Windows
            return True
        if os.path.abspath(port).startswith('/dev/'):
            # Unix
            return True
        return False

class TCPConn:
    def __init__(self, loc):
        if loc == 'simulator':
            host, port = 'localhost', 1983
        else:
            host, port = loc.split(':')
        self._conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._conn.connect((host, int(port)))

    def write(self, b):
        self._conn.send(b)

    def read(self):
        return self._conn.recv(1)

    def close(self):
        return self._conn.close()

    @classmethod
    def accepts(cls, loc):
        return loc == 'simulator' or ':' in loc

class OSD:

    def __init__(self, port, **kwargs):
        self.conn = None
        self.send_buffer = bytearray()
        self.recv_buffer = []
        self.port = port
        self.trace = kwargs.get('trace', False)
        self.debug = self.trace or kwargs.get('debug', False)
        self.baudrate = kwargs.get('baudrate', BAUDRATE)
        self.msp_passthrough = kwargs.get('msp_passthrough', False)
        profile_at = kwargs.get('profile_at')
        if profile_at is not None:
            if isinstance(profile_at, basestring):
                parts = profile_at.split(',')
                if len(parts) != 2:
                    raise ValueError('profile_at string must be in the form int,int, not "{}"'.format(profile_at))
                profile_at = (int(parts[0]), int(parts[1]))
            elif not isinstance(profile_at, list) and not isinstance(profile_at, tuple):
                raise ValueError('profile_at must be a tuple, list or a string in the form "X,Y"')
        self.profile_at = profile_at
        self.info = None

    def open(self):
        '''Open the connection to the OSD'''
        if self.conn is not None:
            self.conn.close()

        if SerialConn.accepts(self.port):
            self.conn = SerialConn(self.port, self.baudrate)
        elif TCPConn.accepts(self.port):
            self.conn = TCPConn(self.port)
        else:
            print("Unknown port type {}".format(self.port))
            return False

        if self.msp_passthrough:
            return self._set_msp_passthrough()
        return True

    def close(self):
        if self.conn is not None:
            self.flush()
            if self.msp_passthrough:
                self._stop_msp_passthrough()
            self.conn.close()
            self.conn = None

    def connect(self, force=False):
        '''Open the connection and retrieve OSD info'''
        if self.is_connected() and not force:
            return True
        if not self.open():
            return False
        resp = self.get_info()
        if not resp or resp.cmd != CMD.INFO:
            print("Invalid CMD.INFO response {}".format(resp))
            return False

        self.info = resp
        if resp.is_bootloader:
            print('FrSky OSD bootloader')
        else:
            print("FrSky OSD {}.{}.{}, {}x{} grid, {}x{} pixels".format(resp.major, resp.minor, resp.patch, resp.gridColumns, resp.gridRows, resp.pixelWidth, resp.pixelHeight))
        return True

    def is_connected(self):
        return self.conn is not None and self.info is not None

    def get_info(self):
        return self.send_frame_sync_resp(CMD.INFO, _int_as_bytes(1))

    def _speaks_v2(self):
        return self.info.major >= 2 or (self.info.major == 1 and self.info.minor >= 99)

    # Font uploading

    def upload_font_char(self, char_addr, char_data):
        data = char_data
        if self.trace:
            print('Uploading character {} {}'.format(char_addr, _format_payload(data)))
        payload = struct.pack('<H', char_addr) + data
        return self.send_frame_sync_resp(CMD.WRITE_FONT, payload)

    def upload_font(self, font, progress=None):
        '''Upload a MAX7456 font from an MCM'''
        header = font.readline().strip()
        if header != b'MAX7456':
            raise RuntimeError("Invalid MAX7456 header")

        data = bytearray()
        chr_addr = 0
        buf = ''
        for ch in font.read():
            if isinstance(ch, int):
                # Python 3
                ch = chr(ch)
            if ch == '\r' or ch == '\n':
                continue
            buf += ch
            if len(buf) == 8:
                b = int(buf, 2)
                data.append(b)
                buf = ''
                if len(data) == 64:
                    self.upload_font_char(chr_addr, data)
                    if progress:
                        progress(chr_addr)
                    data = bytearray()
                    chr_addr += 1

    def read_font_char(self, char_addr):
        payload = struct.pack('<H', char_addr)
        return self.send_frame_sync_resp(CMD.READ_FONT, payload)

    # Firmware flashing

    def flash_firmware(self, f, no_reboot=False, progress=None):
        '''Flash a compatible firmware file'''
        if not no_reboot:
            self.reboot(True)
            time.sleep(1)
        self.flash_firmware_bl(f, progress)

    def erase_firmware(self, no_reboot=False):
        '''Erase firmware from the device (will need an update applied to work)'''
        if not no_reboot:
            self.reboot(True)
            time.sleep(1)
        payload = struct.pack('<L', 0)
        resp = self.send_frame_sync_resp(CMD.WRITE_FLASH, payload)
        self._ensure_write_flash_response(resp, 0)
        self._flash_finish()

    def _flash_finish(self, allow_workaround=False):
        # Signal flash end
        payload = struct.pack('<L', FLASH_WRITE_END)
        resp = self.send_frame_sync_resp(CMD.WRITE_FLASH, payload)
        self._ensure_write_flash_response(resp, 0, allow_workaround=allow_workaround)
        # Reboot
        self.reboot()

    def flash_firmware_bl(self, f, progress=None):
        '''Flash a compatible firmware file, already in BL'''
        rem = f.read()
        total = len(rem)
        addr = 0
        while len(rem) > 0:
            sz = FLASH_WRITE_MAX_BLOCK_SIZE if len(rem) > FLASH_WRITE_MAX_BLOCK_SIZE else len(rem)
            chunk = rem[:sz]
            rem = rem[sz:]
            payload = struct.pack('<L', addr) + chunk
            addr += sz
            resp = self.send_frame_sync_resp(CMD.WRITE_FLASH, payload)
            self._ensure_write_flash_response(resp, addr, allow_workaround=_ALLOW_WORKAROUND and len(rem) == 0)
            if progress:
                progress(1 - float(len(rem)) / total)
            if self.debug:
                print('{} of {} bytes'.format(total - len(rem), total))

        self._flash_finish(allow_workaround=_ALLOW_WORKAROUND)

    def reboot(self, to_bootloader=False):
        '''Perform an OSD reboot, optionally staying into BL mode'''
        payload = [1 if to_bootloader else 0]
        self.send_frame(CMD.REBOOT, payload)
        self.flush_send_buffer()

    # Camera and other settings
    def get_active_camera(self):
        resp = self.send_frame_sync_resp(CMD.GET_ACTIVE_CAMERA)
        return resp.byte_at(0)

    # Transactions

    def transaction_begin(self, profile_at=None):
        profile_at = profile_at = self.profile_at
        if profile_at:
            payload = self._pack_point(profile_at[0], profile_at[1])
            self.send_frame(CMD.TRANSACTION_BEGIN_PROFILED, payload)
        else:
            self.send_frame(CMD.TRANSACTION_BEGIN)

    def transaction_commit(self):
        self.send_frame(CMD.TRANSACTION_COMMIT)
        self.flush_send_buffer()

    # Drawing

    def draw_grid_chr(self, gx, gy, ch, opts=None):
        c = ch
        if isinstance(c, str):
            c = ord(c[0])
        c = int(c)
        opts = opts or 0
        if c < 512 and opts <= 7 and self._speaks_v2():
            cmd = CMD.DRAW_GRID_CHR_2
            val = 0
            val |= (gx & 31) << 0
            val |= (gy & 15) << 5
            val |= (c & 511) << 9
            val |= (opts & 7) << 18
            payload = self._pack_u24(val)
        else:
            cmd = CMD.DRAW_GRID_CHR
            payload = struct.pack('<BBHB', gx, gy, c, opts)
        return self.send_frame(cmd, payload)

    def draw_grid_str(self, gx, gy, s, opts=None):
        opts = opts or 0
        if opts <= 7 and self._speaks_v2():
            cmd = CMD.DRAW_GRID_STR_2
            val = 0
            val |= (gx & 31) << 0
            val |= (gy & 15) << 5
            val |= (opts & 7) << 9
            if len(s) <= 15:
                val |= (len(s) & 15) << 12
                header = self._pack_u16(val)
                payload = header + _str_to_bytes(s)
            else:
                header = self._pack_u16(val)
                payload = header + self._pack_str(s, null_terminated=False)
        else:
            cmd = CMD.DRAW_GRID_STR
            header = struct.pack('<BBB', gx, gy, opts or 0)
            payload = header + self._pack_str(s)
        return self.send_frame(cmd, payload)

    def set_stroke_color(self, color):
        payload = self._pack_color(color)
        return self.send_frame(CMD.SET_STROKE_COLOR, payload)

    def set_fill_color(self, color):
        payload = self._pack_color(color)
        return self.send_frame(CMD.SET_FILL_COLOR, payload)

    def set_stroke_and_fill_color(self, color):
        payload = self._pack_color(color)
        return self.send_frame(CMD.SET_STROKE_AND_FILL_COLOR, payload)

    def set_color_inversion(self, invert):
        payload = self._pack_u8(1 if invert else 0)
        return self.send_frame(CMD.SET_COLOR_INVERSION, payload)

    def set_pixel(self, x, y, color):
        payload = self._pack_point(x, y) + self._pack_color(color)
        return self.send_frame(CMD.SET_PIXEL, payload)

    def set_pixel_to_stroke_color(self, x, y):
        payload = self._pack_point(x, y)
        return self.send_frame(CMD.SET_PIXEL_TO_STROKE_COLOR, payload)

    def set_pixel_to_fill_color(self, x, y):
        payload = self._pack_point(x, y)
        return self.send_frame(CMD.SET_PIXEL_TO_FILL_COLOR, payload)

    def set_stroke_width(self, w):
        payload = self._pack_u8(w)
        return self.send_frame(CMD.SET_STROKE_WIDTH, payload)

    def set_line_outline_type(self, ot):
        if ot < OUTLINE.NONE or ot > OUTLINE.LEFT:
            raise ValueError("Invalid outline type %d" % ot)

        payload = self._pack_u8(ot)
        return self.send_frame(CMD.SET_LINE_OUTLINE_TYPE, payload)

    def set_line_outline_color(self, color):
        payload = self._pack_color(color)
        return self.send_frame(CMD.SET_LINE_OUTLINE_COLOR, payload)

    def clip_to_rect(self, rect):
        payload = self._pack_rect(rect)
        return self.send_frame(CMD.CLIP_TO_RECT, payload)

    def clear_screen(self):
        '''Clear the whole screen'''
        return self.send_frame(CMD.CLEAR_SCREEN)

    def clear_rect(self, rect):
        '''Clear a rect given as (x, y, w, h)'''
        payload = self._pack_rect(rect)
        return self.send_frame(CMD.CLEAR_RECT, payload)

    def drawing_reset(self):
        return self.send_frame(CMD.DRAWING_RESET)

    def draw_bitmap(self, rect, bitmap, opts=None):
        # TODO
        pass

    def draw_bitmap_mask(self, rect, bitmap, color, opts=None):
        # TODO
        pass

    def draw_chr(self, x, y, ch, opts=None):
        c = ch
        if isinstance(c, str):
            c = ord(c[0])
        payload = self._pack_point(x, y) + struct.pack('<HB', int(c), (opts or 0))
        return self.send_frame(CMD.DRAW_CHAR, payload)

    def draw_chr_mask(self, x, y, ch, color, opts=None):
        c = ch
        if isinstance(c, str):
            c = ord(c[0])
        payload = self._pack_point(x, y) + struct.pack('<HBB', int(c), opts or 0, color)
        return self.send_frame(CMD.DRAW_CHAR_MASK, payload)

    def draw_str(self, x, y, s, opts=None):
        self._pack_point(x, y)
        header = self._pack_point(x, y) + struct.pack('<B', opts or 0)
        payload = header + self._pack_str(s)
        return self.send_frame(CMD.DRAW_STRING, payload)

    def draw_str_mask(self, x, y, s, color, opts=None):
        self._pack_point(x, y)
        header = self._pack_point(x, y) + struct.pack('<BB', opts or 0, color)
        payload = header + self._pack_str(s)
        return self.send_frame(CMD.DRAW_STRING_MASK, payload)

    def move_to_point(self, x, y):
        payload = self._pack_point(x, y)
        return self.send_frame(CMD.MOVE_TO_POINT, payload)

    def stroke_line_to_point(self, x, y):
        payload = self._pack_point(x, y)
        return self.send_frame(CMD.STROKE_LINE_TO_POINT, payload)

    def stroke_triangle(self, p1, p2, p3):
        payload = self._pack_point(p1[0], p1[1]) + self._pack_point(p2[0], p2[1]) + self._pack_point(p3[0], p3[1])
        return self.send_frame(CMD.STROKE_TRIANGLE, payload)

    def fill_triangle(self, p1, p2, p3):
        payload = self._pack_point(p1[0], p1[1]) + self._pack_point(p2[0], p2[1]) + self._pack_point(p3[0], p3[1])
        return self.send_frame(CMD.FILL_TRIANGLE, payload)

    def fill_stroke_triangle(self, p1, p2, p3):
        payload = self._pack_point(p1[0], p1[1]) + self._pack_point(p2[0], p2[1]) + self._pack_point(p3[0], p3[1])
        return self.send_frame(CMD.FILL_STROKE_TRIANGLE, payload)

    def stroke_rect(self, r):
        payload = self._pack_rect(r)
        return self.send_frame(CMD.STROKE_RECT, payload)

    def fill_rect(self, r):
        payload = self._pack_rect(r)
        return self.send_frame(CMD.FILL_RECT, payload)

    def fill_stroke_rect(self, r):
        payload = self._pack_rect(r)
        return self.send_frame(CMD.FILL_STROKE_RECT, payload)

    def stroke_ellipse_in_rect(self, r):
        payload = self._pack_rect(r)
        return self.send_frame(CMD.STROKE_ELLIPSE_IN_RECT, payload)

    def fill_ellipse_in_rect(self, r):
        payload = self._pack_rect(r)
        return self.send_frame(CMD.FILL_ELLIPSE_IN_RECT, payload)

    def fill_stroke_ellipse_in_rect(self, r):
        payload = self._pack_rect(r)
        return self.send_frame(CMD.FILL_STROKE_ELLIPSE_IN_RECT, payload)

    # CTM

    def ctm_reset(self):
        self.send_frame(CMD.CTM_RESET)

    def ctm_set(self, m11, m12, m21, m22, m31, m32):
        payload = struct.pack('<ffffff', m11, m12, m21, m22, m31, m32)
        return self.send_frame(CMD.CTM_SET, payload)

    def ctm_translate(self, tx, ty):
        payload = struct.pack('<ff', tx, ty)
        return self.send_frame(CMD.CTM_TRANSLATE, payload)

    def ctm_translate_rev(self, tx, ty):
        payload = struct.pack('<ff', tx, ty)
        return self.send_frame(CMD.CTM_TRANSLATE_REV, payload)

    def ctm_scale(self, sx, sy):
        payload = struct.pack('<ff', sx, sy)
        return self.send_frame(CMD.CTM_SCALE, payload)

    def ctm_rotate(self, r):
        payload = struct.pack('<f', r)
        return self.send_frame(CMD.CTM_ROTATE, payload)

    # Context

    def context_push(self):
        self.send_frame(CMD.CONTEXT_PUSH)

    def context_pop(self):
        self.send_frame(CMD.CONTEXT_POP)

    # Widgets

    def _map_wid(self, idx, min, max):
        wid = min + idx
        if wid > max:
            raise ValueError('this widget\'s index must between 0 and {}'.format(range(max - min + 1)))
        return wid

    def _widget_set_config(self, wid, config):
        payload = struct.pack('<B', wid) + config
        resp = self.send_frame_sync_resp(CMD.WIDGET_SET_CONFIG, payload)
        if isinstance(resp, ResponseError):
            raise RemoteResponseError(resp, 'error configuring widget {}: {}'.format(wid, resp.error_code))

    def _widget_draw(self, wid, data):
        payload = struct.pack('<B', wid) + data
        return self.send_frame(CMD.WIDGET_DRAW, payload)

    def _widget_erase(self, wid):
        payload = struct.pack('<B', wid)
        return self.send_frame(CMD.WIDGET_ERASE, payload)

    def widget_ahi_set_config(self, r, style, crosshair_margin, stroke_width=1, options=0):
        config = self._pack_rect(r) + struct.pack('<BBBB', style, options, crosshair_margin, stroke_width)
        return self._widget_set_config(WIDGETS.AHI, config)

    def widget_ahi_draw(self, pitch, roll):
        data = self._pack_point(pitch, roll)
        return self._widget_draw(WIDGETS.AHI, data)

    def widget_sidebar_set_config(self, idx, r, options, divisions, per_division, unit):
        wid = self._map_wid(idx, WIDGETS.SIDEBAR_0, WIDGETS.SIDEBAR_1)
        config = self._pack_rect(r) + struct.pack('<BBH', options, divisions, per_division) + self._pack_unit(unit)
        return self._widget_set_config(wid, config)

    def widget_sidebar_draw(self, idx, value):
        wid = self._map_wid(idx, WIDGETS.SIDEBAR_0, WIDGETS.SIDEBAR_1)
        data = self._pack_i24(value)
        return self._widget_draw(wid, data)

    def widget_graph_set_config(self, idx, r, options=None, nlabels=0, label_width=0, unit=None, initial_scale=None):
        wid = self._map_wid(idx, WIDGETS.GRAPH_0, WIDGETS.GRAPH_3)
        options = options or 0
        initial_scale = initial_scale or 0
        config = self._pack_rect(r) + struct.pack('<BBBB', options, nlabels, label_width, initial_scale) + self._pack_unit(unit)
        return self._widget_set_config(wid, config)

    def widget_graph_draw(self, idx, value):
        wid = self._map_wid(idx, WIDGETS.GRAPH_0, WIDGETS.GRAPH_3)
        data = self._pack_i24(value)
        return self._widget_draw(wid, data)

    def widget_chargauge_set_config(self, idx, p, c):
        wid = self._map_wid(idx, WIDGETS.CHARGAUGE_0, WIDGETS.CHARGAUGE_3)
        config = self._pack_point(p[0], p[1]) + self._pack_u16(c)
        return self._widget_set_config(wid, config)

    def widget_chargauge_draw(self, idx, value):
        wid = self._map_wid(idx, WIDGETS.CHARGAUGE_0, WIDGETS.CHARGAUGE_3)
        data = self._pack_u8(value)
        return self._widget_draw(wid, data)

    # VM
    def _vm_storage_size(self):
        resp = self.send_frame_sync_resp(CMD.VM_STORAGE_SIZE)
        if isinstance(resp, ResponseError):
            raise RemoteResponseError(resp, 'error retrieving storage size: {}'.format(resp.error_code))
        size = struct.unpack('<L', resp.payload)[0]
        return size

    def _vm_storage_header_size(self):
        return 8

    def _vm_max_transfer_block_size(self):
        return 64

    def _pack_upload_blob(self, offset, blob):
        return struct.pack('<L', offset) + self._pack_blob(blob)

    def _upload_resp_offset(self, resp):
        if isinstance(resp, ResponseError):
            raise RemoteResponseError(resp, 'error retrieving next offset to upload: {}'.format(resp.error_code))
        return struct.unpack('<L', resp.payload)[0]

    def upload_program(self, f):
        data = f.read()
        header_size = self._vm_storage_header_size()
        total_size = len(data) + header_size
        max_size = self._vm_storage_size() - header_size
        if len(data) > max_size:
            raise ValueError('can\'t upload program of {} bytes, maximum size is {}'.format(len(data), max_size))
        crc = self._crc32_ieee(data)
        blob = struct.pack('<LL', total_size, crc)
        payload = self._pack_upload_blob(0, blob)
        resp = self.send_frame_sync_resp(CMD.VM_STORAGE_WRITE, payload)
        offset = self._upload_resp_offset(resp)
        rem = len(data)
        while rem > 0:
            s = min(self._vm_max_transfer_block_size(), rem)
            data_offset = offset - header_size
            chunk = data[data_offset:data_offset+s]
            rem -= len(chunk)
            payload = self._pack_upload_blob(offset, chunk)
            resp = self.send_frame_sync_resp(CMD.VM_STORAGE_WRITE, payload)
            offset = self._upload_resp_offset(resp)

    def download_program(self, f):
        # Read the header
        header_size = self._vm_storage_header_size()
        payload = struct.pack('<LL', 0, header_size)
        resp = self.send_frame_sync_resp(CMD.VM_STORAGE_READ, payload)
        size, crc = struct.unpack('<LL', resp.payload)
        if size > self._vm_storage_size():
            raise RuntimeError('no valid data found in the vm storage')
        rem = size - header_size
        offset = header_size
        while rem > 0:
            s = min(self._vm_max_transfer_block_size(), rem)
            payload = struct.pack('<LL', offset, s)
            resp = self.send_frame_sync_resp(CMD.VM_STORAGE_READ, payload)
            f.write(resp.payload)
            offset += s
            rem -= s

    def start_program(self):
        resp = self.send_frame_sync_resp(CMD.VM_START)
        if isinstance(resp, ResponseError):
            raise RemoteResponseError(resp, 'error starting program: {}'.format(resp.error_code))
        return struct.unpack('<L', resp.payload)[0]

    def run_program(self, f):
        try:
            self.upload_program(f)
        except RemoteResponseError as e:
            if e.resp.error_code != -9:
                # -9 means the same program was already
                # uploaded, so we can proceed with starting
                raise
        self.start_program()

    def _vm_lookup_symbol(self, name):
        payload = self._pack_str(name)
        resp = self.send_frame_sync_resp(CMD.VM_LOOKUP_SYMBOL, payload)
        if isinstance(resp, ResponseError):
            raise RemoteResponseError(resp, 'error looking up symbol "{}": {}'.format(name, resp.error_code))
        return struct.unpack('<h', resp.payload)[0]

    def run_function(self, name, args=None, reply=True):
        args = args or []
        sym = self._vm_lookup_symbol(name)
        sym = sym << 1 | 1 if reply else 0
        payload = self._pack_uvarint(sym)
        payload += self._pack_uvarint(len(args))
        for item in args:
            if isinstance(item, str if sys.version_info[0] >= 3 else basestring):
                if '.' in item:
                    item = float(item)
                else:
                    item = int(item)
            if type(item) is int:
                payload += self._pack_u32(item)
            elif type(item) is float:
                payload += struct.pack('<f', item)
            else:
                raise ValueError('can\'t encode argument {} of type {}'.format(item, type(item)))

        if reply:
            resp = self.send_frame_sync_resp(CMD.VM_EXEC, payload)
            return struct.unpack('<L', resp.payload)[0]
        else:
            self.send_frame(CMD.VM_EXEC, payload)

    # Raw frame handling

    def send_frame_sync_resp(self, cmd, payload=None):
        self.send_frame(cmd, payload)
        self.flush_send_buffer()
        if not self._expect_marker('$', skip=1000):
            return None
        if not self._expect_marker('A'):
            return None

        crc = 0
        payload_size = 0
        shift = 0
        while True:
            b = self._recv_byte()
            crc = self._crc8_dvb_s2(crc, b)
            payload_size |= b << shift
            if payload_size > 2048:
                raise RuntimeError("payload size of {} is too big".format(payload_size))
            if b < 0x80:
                break
            shift += 7
        payload = bytearray()
        for ii in range(payload_size):
            b = self._recv_byte()
            crc = self._crc8_dvb_s2(crc, b)
            payload.append(b)

        ccrc = self._recv_byte()
        if crc != ccrc:
            print("Invalid crc %d, expecting %d" % (ccrc, crc))
            return None

        # OSD responses are never bundled
        cmd = payload[0]
        resp = Response.decode(cmd, payload[1:])
        if self.debug:
            print('RESP <<= {}'.format(resp))
        return resp

    def send_frame(self, cmd, payload=None):
        if self.debug:
            print("CMD {} =>> {}".format(cmd, _format_payload(payload)))
        if len(payload or []) + 1 + len(self.send_buffer) > MAX_SEND_BUFFER_SIZE:
            self.flush_send_buffer()

        self.send_buffer.append(cmd)
        if payload:
            self.send_buffer.extend(payload)

    def set_data_rate(self, dr):
        dr = dr or BAUDRATE
        payload = self._pack_u32(dr)
        resp = self.send_frame_sync_resp(CMD.SET_DATA_RATE, payload)
        new_dr = struct.unpack('<I', resp.payload)[0]
        if new_dr != self.baudrate:
            if self.trace:
                print("changing baudrate from {} to {}".format(self.baudrate, new_dr))
            self.baudrate = new_dr
            self.open()
        return self.baudrate

    # MSP

    def _msp_req(self, cmd, payload=None):
        payload = payload or []
        self._conn_write(b'$M<')
        size = len(payload)
        self._conn_write(size)
        crc = size ^ cmd
        self._conn_write(cmd)
        for b in payload:
            crc ^= b
            self._conn_write(b)
        self._conn_write(crc)

        self._expect_marker('$')
        self._expect_marker('M')
        self._expect_marker('>')

        resp_size = self._recv_byte()
        resp_cmd = self._recv_byte()
        if cmd != resp_cmd:
            print('invalid msp response to {} to request {}', resp_cmd, cmd)
            return None

        resp_crc = resp_size ^ resp_cmd
        resp = bytearray()
        for ii in range(0, resp_size):
            b = self._recv_byte()
            resp.append(b)
            resp_crc ^= b

        resp_recv_crc = self._recv_byte()
        if resp_crc != resp_recv_crc:
            print('received invalid MSP crc {}, expecting {}', resp_recv_crc, resp_crc)
            return None

        return resp

    def _set_msp_passthrough(self):
        variant = self._msp_req(2)
        if not variant:
            return False

        # Function ID for FrSky OSD is 16 in BF and 20 in INAV
        frsky_osd_serial_fn = 16 if str(variant) == 'BTFL' else 20
        resp = self._msp_req(245, bytearray([0xfe, frsky_osd_serial_fn]))
        return resp and resp[0] != 0

    def _stop_msp_passthrough(self):
        time.sleep(1)
        self._conn_write(b'+++')
        time.sleep(1)
        self._conn_write(b'ATH')

    def _ensure_write_flash_response(self, resp, addr, allow_workaround=False):
        if not isinstance(resp, ResponseWriteFlash):
            if allow_workaround and isinstance(resp, ResponseError) and resp.request_cmd == CMD.WRITE_FLASH:
                print('WARNING: Applying workaround for bootloader')
                return
            raise RuntimeError('invalid WRITE_FLASH response {}'.format(resp))
        if resp.addr != addr:
            raise RuntimeError('unexpected WRITE_FLASH adddr response {}, expecting {}'.format(resp.addr, addr))

    # Pack/unpack

    def _pack_u8(self, val):
        return struct.pack('<B', val & 0xFF)

    def _pack_u16(self, val):
        return struct.pack('<H', val)

    def _pack_i24(self, val):
        return struct.pack('<i', val)[:3]

    def _pack_u24(self, val):
        return self._pack_u32(val)[:3]

    def _pack_u32(self, val):
        return struct.pack('<I', val)

    def _pack_color(self, color):
        if color < COLOR._MIN or color > COLOR._MAX:
            raise RuntimeError("Invalid color %d" % color)
        return self._pack_u8(color)

    def _pack_coord(self, c):
        i = int(c)
        if i < 0:
            i += 1 << 32
        return i & 0xfff

    def _pack_point(self, x, y):
        return struct.pack('<L', self._pack_coord(y) << 12 | self._pack_coord(x))[:3]

    def _pack_size(self, w, h):
        return self._pack_point(w, h)

    def _pack_rect(self, r):
        x, y, w, h = r
        return self._pack_point(x, y) + self._pack_size(w, h)

    def _pack_uvarint(self, x):
        data = bytearray()
        while x >= 0x80:
            data.append((x & 0xFF) | 0x80)
            x = x >> 7
        data.append(x & 0xFF)
        return data

    def _pack_blob(self, b):
        size = self._pack_uvarint(len(b))
        return size + b

    def _pack_str(self, s, null_terminated=True):
        b = _str_to_bytes(s)
        if null_terminated:
            b += _int_as_bytes(0)
        return self._pack_blob(b)

    def _pack_unit(self, u):
        if u is None:
            return struct.pack('<LL', 0, 0)
        return struct.pack('<HHHH', u.scale, u.symbol, u.divisor, u.divided_symbol)

    def flush(self):
        self.flush_send_buffer()

    def flush_send_buffer(self):
        self._conn_write(b'$')
        self._conn_write(b'A')
        crc = 0
        length = self._pack_uvarint(len(self.send_buffer))
        for v in length:
            crc = self._send_crc_byte(crc, v & 0xff)
        for b in self.send_buffer:
            crc = self._send_crc_byte(crc, b & 0xff)
        self._conn_write(crc)
        self.send_buffer = bytearray()

    def _send_crc_byte(self, crc, b):
        crc = self._crc8_dvb_s2(crc, b)
        self._conn_write(b)
        return crc

    def _recv_byte(self):
        r = self.conn.read()
        b = r[0]
        if isinstance(b, str):
            b = struct.unpack('B', b)[0]
        if self.trace:
            print('R<< {0}\t({0:#04x} = {1!r})'.format(b, chr(b)))
        return b

    def _expect_marker(self, mk, skip = 1):
        while skip > 0:
            b = self._recv_byte()
            if b == ord(mk):
                return True
            skip -= 1
        print("Unexpected marker {} ({}), expecting {}".format(chr(b), b, mk))
        return False

    def _conn_write(self, b):
        if not isinstance(b, bytes):
            b = _int_as_bytes(b)
        if self.trace:
            for bb in _bytes_as_ints(b):
                print('W>> {0}\t({0:#04x} = {1!r})'.format(bb, chr(bb)))
        self.conn.write(b)

    def _crc8_dvb_s2(self, crc, b):
        crc ^= b
        for ii in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0xD5) & 0xff
            else:
                crc = (crc << 1) & 0xff
        return crc

    def _crc32_ieee(self, data):
        # Python 2 will return a signed value that
        # we need to convert to unsigned. For Python3
        # the modulus doesn't change the value since
        # by definition it's always < 1<<32
        return binascii.crc32(data) % (1 << 32)

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('port', type=str, help='OSD port. Supports both path to serial port path or host:port')
    parser.add_argument('--debug', default=False, action='store_true', dest='debug', help='Print debugging information')
    parser.add_argument('--trace', default=False, action='store_true', dest='trace', help='Print all data sent/received')
    parser.add_argument('--upload-font', dest='upload_font', help='Font file to upload')
    parser.add_argument('--upload-program', dest='upload_program', help='Program file to upload for the VM')
    parser.add_argument('--download-program', dest='download_program', help='Download program from the VM and store it in the given file')
    parser.add_argument('--start-program', default=False, action='store_true', dest='start_program', help='Download program from the VM and store it in the given file')
    parser.add_argument('--erase', default=False, action='store_true', dest='erase', help='Erase firmware')
    parser.add_argument('--flash', dest='flash', help='Update file to flash')
    parser.add_argument('--flash-nr', default=False, action='store_true', dest='flash_no_reboot', help='Skip rebooting into bootloader mode before flashing')
    parser.add_argument('--hw-version', default=False, action='store_true', dest='hw_version', help='Connect to OSD and print hardware version')
    parser.add_argument('--reboot', default=False, action='store_true', dest='reboot', help='Reboot the OSD')
    parser.add_argument('--reboot-to-bootloader', default=False, action='store_true', dest='reboot_to_bootloader', help='Reboot the OSD and stay in bootloader mode')
    parser.add_argument('--msp-passthrough', default=False, action='store_true', dest='msp_passthrough', help='Use MSP passthrough via a INAV/Betaflight to connect to the OSD')
    parser.add_argument('--run', dest='run', help='Upload a program to the VM and start it')
    parser.add_argument('--run-function', dest='run_function', help='Run a function from the VM program. Syntax is <name>[,arg1]...[,argn]')
    args = parser.parse_args()

    osd = OSD(args.port, msp_passthrough=args.msp_passthrough, debug=args.debug, trace=args.trace)

    if args.reboot or args.reboot_to_bootloader:
        osd.open()
        osd.reboot(args.reboot_to_bootloader)

    if args.erase:
        osd.open()
        osd.erase_firmware()

    if args.flash:
        osd.open()
        with open(args.flash, 'rb') as f:
            osd.flash_firmware(f, args.flash_no_reboot)

    if args.upload_font:
        osd.connect()
        with open(args.upload_font, 'rb') as f:
            osd.upload_font(f)

    if args.upload_program:
        osd.connect()
        with open(args.upload_program, 'rb') as f:
            osd.upload_program(f)

    if args.download_program:
        osd.connect()
        with open(args.download_program, 'wb') as f:
            osd.download_program(f)

    if args.start_program:
        osd.connect()
        osd.start_program()

    if args.hw_version:
        osd.connect()

    if args.run:
        osd.open()
        with open(args.run, 'rb') as f:
            osd.run_program(f)

    if args.run_function:
        osd.connect()
        values = args.run_function.split(',', 1)
        args = None
        if len(values) > 1:
            args = values[1].split(',')
        ret = osd.run_function(values[0], args)
        if ret is not None:
            print('return value: {}'.format(ret))

    osd.close()
