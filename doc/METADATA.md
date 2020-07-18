Character metadata in FrSky OSD
===============================

In FrSky OSD, each character is stored as 64 bytes, only the first 54 are visible data.
The rest can be used to store and retrieve arbitrary metadata.

To manage fonts with metadata, you can use https://github.com/fiam/max7456tool, which is a
command line tool to generate `.mcm` charsets from `.png` files and also supports supplying
additional data and metadata via `.yaml` files.

While entirely optional, the widgets system uses this metadata to understand your font better
and use the available screen real state more efficiently (e.g. if the minus symbol doesn't take
the whole with of a chracter, it can be displayed more closely to the digits).

While reading the metadata, FrSky OSD will read the non visible bytes from the start looking
for some special markers, but it will stop on the first transparent byte it finds (as long as
it's not within a metadata block) since other tools for editing `.mcm` fonts will always fill
this are with transparent bytes (`0x55 = U`).

# Supported metadata types

The following types of metadata are read and used by the OSD within the widgets system:

## size

The size metadata type indicates just a size. It's identified by the byte `s` followed by
the struct:

```c
typedef struct osd_font_char_metadata_size_s
{
    uint8_t sz;
} __attribute__((packed)) osd_font_char_metadata_size_t;
```

It can be represented in yaml as:

```yaml
<char_number>:
    metadata:
        - s: 's'
        - u8: value
```

# offset

The offset metadata type encodes a signed offset with 2 coordinates. It's identified by the
byte `o` followed by the struct:

```c
typedef struct osd_font_char_metadata_offset_s
{
    int8_t x;
    int8_t y;
} __attribute__((packed)) osd_font_char_metadata_offset_t;
```

It can be represented in yaml as:

```yaml
<char_number>:
    metadata:
        - s: 'o'
        - i8: value_x
        - i8: value_y
```

# rect

The rect type encodes a rect with unsigned origin and size, so it's usually interpreted as a rect
within the character. It's identified by the byte `r` followed by the struct

```c
typedef struct osd_font_char_metadata_rect_s
{
    uint8_t x;
    uint8_t y;
    uint8_t w;
    uint8_t h;
} __attribute__((packed)) osd_font_char_metadata_rect_t;
```

It can be represented in yaml as:

```yaml
<char_number>:
    metadata:
        - s: 'r'
        - u8: value_x
        - u8: value_y
        - u8: value_w
        - u8: value_h
```

# colors

Encodes a list of 4 2-bit colors into a single byte. It's identified by the byte `c` followed by the struct:

```c
typedef struct osd_font_char_metadata_colors_s
{
    uint8_t color0 : 2;
    uint8_t color1 : 2;
    uint8_t color2 : 2;
    uint8_t color3 : 2;
} __attribute__((packed)) osd_font_char_metadata_colors_t;
```

It can be represented in yaml as:

```yaml
<char_number>:
    metadata:
        - s: 'c'
        - c: WHITE,BLACK,TRANSPARENT,GRAY
```