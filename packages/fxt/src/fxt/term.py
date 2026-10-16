'''
Misc terminal utility methods/etc.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)


#!================================================================================(80)
#! imports
#!--------------------------------------------------------------------------------(80)
import logging
from getch import getch
#from rich.console import Console
from rich import print


__all__ = [
    'Colors',
    'clear',
    'pause'
]


#!================================================================================(80)
#! utils
#!--------------------------------------------------------------------------------(80)
def pause(msg="Press any key to continue~"):
    """ Provides getch() functionality. Works on linux, not sure about windows.
    """
    print(f"[bold bright_yellow]{msg}[/]")
    getch()
#

def clear():
    """ Clear's the terminal in a cross-platform kind of way. 
        
        I'm using subprocess.call() with the clear command as it is the only method
        that works well in the vscode console (based on my testing).
    """
    # from rich.console import Console
    # console = Console()
    # console.clear()
    from subprocess import call
    import os
    cmd = "cls" if os.name == "nt" else "clear"
    call(cmd, shell=True)
#


#!================================================================================(80)
#! constants
#!--------------------------------------------------------------------------------(80)
class Colors:
    """Rich standard color names as constants.

        Source: https://rich.readthedocs.io/en/stable/appendix/colors.html
        Each value is the color's name as a string. Trailing comments give the hex and
        rgb values where the docs list them (the first 16 depend on the terminal theme).
    """
    #~ standard colors (defined by the terminal, so no fixed hex/rgb)
    BLACK               = "black"
    RED                 = "red"
    GREEN               = "green"
    YELLOW              = "yellow"
    BLUE                = "blue"
    MAGENTA             = "magenta"
    CYAN                = "cyan"
    WHITE               = "white"
    BRIGHT_BLACK        = "bright_black"
    BRIGHT_RED          = "bright_red"
    BRIGHT_GREEN        = "bright_green"
    BRIGHT_YELLOW       = "bright_yellow"
    BRIGHT_BLUE         = "bright_blue"
    BRIGHT_MAGENTA      = "bright_magenta"
    BRIGHT_CYAN         = "bright_cyan"
    BRIGHT_WHITE        = "bright_white"

    #~ 8-bit colors
    GREY0               = "grey0"                # #000000  rgb(0,0,0)
    NAVY_BLUE           = "navy_blue"            # #00005f  rgb(0,0,95)
    DARK_BLUE           = "dark_blue"            # #000087  rgb(0,0,135)
    BLUE3               = "blue3"                # #0000d7  rgb(0,0,215)
    BLUE1               = "blue1"                # #0000ff  rgb(0,0,255)
    DARK_GREEN          = "dark_green"           # #005f00  rgb(0,95,0)
    DEEP_SKY_BLUE4      = "deep_sky_blue4"       # #005faf  rgb(0,95,175)
    DODGER_BLUE3        = "dodger_blue3"         # #005fd7  rgb(0,95,215)
    DODGER_BLUE2        = "dodger_blue2"         # #005fff  rgb(0,95,255)
    GREEN4              = "green4"               # #008700  rgb(0,135,0)
    SPRING_GREEN4       = "spring_green4"        # #00875f  rgb(0,135,95)
    TURQUOISE4          = "turquoise4"           # #008787  rgb(0,135,135)
    DEEP_SKY_BLUE3      = "deep_sky_blue3"       # #0087d7  rgb(0,135,215)
    DODGER_BLUE1        = "dodger_blue1"         # #0087ff  rgb(0,135,255)
    DARK_CYAN           = "dark_cyan"            # #00af87  rgb(0,175,135)
    LIGHT_SEA_GREEN     = "light_sea_green"      # #00afaf  rgb(0,175,175)
    DEEP_SKY_BLUE2      = "deep_sky_blue2"       # #00afd7  rgb(0,175,215)
    DEEP_SKY_BLUE1      = "deep_sky_blue1"       # #00afff  rgb(0,175,255)
    GREEN3              = "green3"               # #00d700  rgb(0,215,0)
    SPRING_GREEN3       = "spring_green3"        # #00d75f  rgb(0,215,95)
    CYAN3               = "cyan3"                # #00d7af  rgb(0,215,175)
    DARK_TURQUOISE      = "dark_turquoise"       # #00d7d7  rgb(0,215,215)
    TURQUOISE2          = "turquoise2"           # #00d7ff  rgb(0,215,255)
    GREEN1              = "green1"               # #00ff00  rgb(0,255,0)
    SPRING_GREEN2       = "spring_green2"        # #00ff5f  rgb(0,255,95)
    SPRING_GREEN1       = "spring_green1"        # #00ff87  rgb(0,255,135)
    MEDIUM_SPRING_GREEN = "medium_spring_green"  # #00ffaf  rgb(0,255,175)
    CYAN2               = "cyan2"                # #00ffd7  rgb(0,255,215)
    CYAN1               = "cyan1"                # #00ffff  rgb(0,255,255)
    PURPLE4             = "purple4"              # #5f00af  rgb(95,0,175)
    PURPLE3             = "purple3"              # #5f00d7  rgb(95,0,215)
    BLUE_VIOLET         = "blue_violet"          # #5f00ff  rgb(95,0,255)
    GREY37              = "grey37"               # #5f5f5f  rgb(95,95,95)
    MEDIUM_PURPLE4      = "medium_purple4"       # #5f5f87  rgb(95,95,135)
    SLATE_BLUE3         = "slate_blue3"          # #5f5fd7  rgb(95,95,215)
    ROYAL_BLUE1         = "royal_blue1"          # #5f5fff  rgb(95,95,255)
    CHARTREUSE4         = "chartreuse4"          # #5f8700  rgb(95,135,0)
    PALE_TURQUOISE4     = "pale_turquoise4"      # #5f8787  rgb(95,135,135)
    STEEL_BLUE          = "steel_blue"           # #5f87af  rgb(95,135,175)
    STEEL_BLUE3         = "steel_blue3"          # #5f87d7  rgb(95,135,215)
    CORNFLOWER_BLUE     = "cornflower_blue"      # #5f87ff  rgb(95,135,255)
    DARK_SEA_GREEN4     = "dark_sea_green4"      # #5faf5f  rgb(95,175,95)
    CADET_BLUE          = "cadet_blue"           # #5fafaf  rgb(95,175,175)
    SKY_BLUE3           = "sky_blue3"            # #5fafd7  rgb(95,175,215)
    CHARTREUSE3         = "chartreuse3"          # #5fd700  rgb(95,215,0)
    SEA_GREEN3          = "sea_green3"           # #5fd787  rgb(95,215,135)
    AQUAMARINE3         = "aquamarine3"          # #5fd7af  rgb(95,215,175)
    MEDIUM_TURQUOISE    = "medium_turquoise"     # #5fd7d7  rgb(95,215,215)
    STEEL_BLUE1         = "steel_blue1"          # #5fd7ff  rgb(95,215,255)
    SEA_GREEN2          = "sea_green2"           # #5fff5f  rgb(95,255,95)
    SEA_GREEN1          = "sea_green1"           # #5fffaf  rgb(95,255,175)
    DARK_SLATE_GRAY2    = "dark_slate_gray2"     # #5fffff  rgb(95,255,255)
    DARK_RED            = "dark_red"             # #870000  rgb(135,0,0)
    DARK_MAGENTA        = "dark_magenta"         # #8700af  rgb(135,0,175)
    ORANGE4             = "orange4"              # #875f00  rgb(135,95,0)
    LIGHT_PINK4         = "light_pink4"          # #875f5f  rgb(135,95,95)
    PLUM4               = "plum4"                # #875f87  rgb(135,95,135)
    MEDIUM_PURPLE3      = "medium_purple3"       # #875fd7  rgb(135,95,215)
    SLATE_BLUE1         = "slate_blue1"          # #875fff  rgb(135,95,255)
    WHEAT4              = "wheat4"               # #87875f  rgb(135,135,95)
    GREY53              = "grey53"               # #878787  rgb(135,135,135)
    LIGHT_SLATE_GREY    = "light_slate_grey"     # #8787af  rgb(135,135,175)
    MEDIUM_PURPLE       = "medium_purple"        # #8787d7  rgb(135,135,215)
    LIGHT_SLATE_BLUE    = "light_slate_blue"     # #8787ff  rgb(135,135,255)
    YELLOW4             = "yellow4"              # #87af00  rgb(135,175,0)
    DARK_SEA_GREEN      = "dark_sea_green"       # #87af87  rgb(135,175,135)
    LIGHT_SKY_BLUE3     = "light_sky_blue3"      # #87afd7  rgb(135,175,215)
    SKY_BLUE2           = "sky_blue2"            # #87afff  rgb(135,175,255)
    CHARTREUSE2         = "chartreuse2"          # #87d700  rgb(135,215,0)
    PALE_GREEN3         = "pale_green3"          # #87d787  rgb(135,215,135)
    DARK_SLATE_GRAY3    = "dark_slate_gray3"     # #87d7d7  rgb(135,215,215)
    SKY_BLUE1           = "sky_blue1"            # #87d7ff  rgb(135,215,255)
    CHARTREUSE1         = "chartreuse1"          # #87ff00  rgb(135,255,0)
    LIGHT_GREEN         = "light_green"          # #87ff87  rgb(135,255,135)
    AQUAMARINE1         = "aquamarine1"          # #87ffd7  rgb(135,255,215)
    DARK_SLATE_GRAY1    = "dark_slate_gray1"     # #87ffff  rgb(135,255,255)
    DEEP_PINK4          = "deep_pink4"           # #af005f  rgb(175,0,95)
    MEDIUM_VIOLET_RED   = "medium_violet_red"    # #af0087  rgb(175,0,135)
    DARK_VIOLET         = "dark_violet"          # #af00d7  rgb(175,0,215)
    PURPLE              = "purple"               # #af00ff  rgb(175,0,255)
    MEDIUM_ORCHID3      = "medium_orchid3"       # #af5faf  rgb(175,95,175)
    MEDIUM_ORCHID       = "medium_orchid"        # #af5fd7  rgb(175,95,215)
    DARK_GOLDENROD      = "dark_goldenrod"       # #af8700  rgb(175,135,0)
    ROSY_BROWN          = "rosy_brown"           # #af8787  rgb(175,135,135)
    GREY63              = "grey63"               # #af87af  rgb(175,135,175)
    MEDIUM_PURPLE2      = "medium_purple2"       # #af87d7  rgb(175,135,215)
    MEDIUM_PURPLE1      = "medium_purple1"       # #af87ff  rgb(175,135,255)
    DARK_KHAKI          = "dark_khaki"           # #afaf5f  rgb(175,175,95)
    NAVAJO_WHITE3       = "navajo_white3"        # #afaf87  rgb(175,175,135)
    GREY69              = "grey69"               # #afafaf  rgb(175,175,175)
    LIGHT_STEEL_BLUE3   = "light_steel_blue3"    # #afafd7  rgb(175,175,215)
    LIGHT_STEEL_BLUE    = "light_steel_blue"     # #afafff  rgb(175,175,255)
    DARK_OLIVE_GREEN3   = "dark_olive_green3"    # #afd75f  rgb(175,215,95)
    DARK_SEA_GREEN3     = "dark_sea_green3"      # #afd787  rgb(175,215,135)
    LIGHT_CYAN3         = "light_cyan3"          # #afd7d7  rgb(175,215,215)
    LIGHT_SKY_BLUE1     = "light_sky_blue1"      # #afd7ff  rgb(175,215,255)
    GREEN_YELLOW        = "green_yellow"         # #afff00  rgb(175,255,0)
    DARK_OLIVE_GREEN2   = "dark_olive_green2"    # #afff5f  rgb(175,255,95)
    PALE_GREEN1         = "pale_green1"          # #afff87  rgb(175,255,135)
    DARK_SEA_GREEN2     = "dark_sea_green2"      # #afffaf  rgb(175,255,175)
    PALE_TURQUOISE1     = "pale_turquoise1"      # #afffff  rgb(175,255,255)
    RED3                = "red3"                 # #d70000  rgb(215,0,0)
    DEEP_PINK3          = "deep_pink3"           # #d70087  rgb(215,0,135)
    MAGENTA3            = "magenta3"             # #d700d7  rgb(215,0,215)
    DARK_ORANGE3        = "dark_orange3"         # #d75f00  rgb(215,95,0)
    INDIAN_RED          = "indian_red"           # #d75f5f  rgb(215,95,95)
    HOT_PINK3           = "hot_pink3"            # #d75f87  rgb(215,95,135)
    HOT_PINK2           = "hot_pink2"            # #d75faf  rgb(215,95,175)
    ORCHID              = "orchid"               # #d75fd7  rgb(215,95,215)
    ORANGE3             = "orange3"              # #d78700  rgb(215,135,0)
    LIGHT_SALMON3       = "light_salmon3"        # #d7875f  rgb(215,135,95)
    LIGHT_PINK3         = "light_pink3"          # #d78787  rgb(215,135,135)
    PINK3               = "pink3"                # #d787af  rgb(215,135,175)
    PLUM3               = "plum3"                # #d787d7  rgb(215,135,215)
    VIOLET              = "violet"               # #d787ff  rgb(215,135,255)
    GOLD3               = "gold3"                # #d7af00  rgb(215,175,0)
    LIGHT_GOLDENROD3    = "light_goldenrod3"     # #d7af5f  rgb(215,175,95)
    TAN                 = "tan"                  # #d7af87  rgb(215,175,135)
    MISTY_ROSE3         = "misty_rose3"          # #d7afaf  rgb(215,175,175)
    THISTLE3            = "thistle3"             # #d7afd7  rgb(215,175,215)
    PLUM2               = "plum2"                # #d7afff  rgb(215,175,255)
    YELLOW3             = "yellow3"              # #d7d700  rgb(215,215,0)
    KHAKI3              = "khaki3"               # #d7d75f  rgb(215,215,95)
    LIGHT_YELLOW3       = "light_yellow3"        # #d7d7af  rgb(215,215,175)
    GREY84              = "grey84"               # #d7d7d7  rgb(215,215,215)
    LIGHT_STEEL_BLUE1   = "light_steel_blue1"    # #d7d7ff  rgb(215,215,255)
    YELLOW2             = "yellow2"              # #d7ff00  rgb(215,255,0)
    DARK_OLIVE_GREEN1   = "dark_olive_green1"    # #d7ff87  rgb(215,255,135)
    DARK_SEA_GREEN1     = "dark_sea_green1"      # #d7ffaf  rgb(215,255,175)
    HONEYDEW2           = "honeydew2"            # #d7ffd7  rgb(215,255,215)
    LIGHT_CYAN1         = "light_cyan1"          # #d7ffff  rgb(215,255,255)
    RED1                = "red1"                 # #ff0000  rgb(255,0,0)
    DEEP_PINK2          = "deep_pink2"           # #ff005f  rgb(255,0,95)
    DEEP_PINK1          = "deep_pink1"           # #ff00af  rgb(255,0,175)
    MAGENTA2            = "magenta2"             # #ff00d7  rgb(255,0,215)
    MAGENTA1            = "magenta1"             # #ff00ff  rgb(255,0,255)
    ORANGE_RED1         = "orange_red1"          # #ff5f00  rgb(255,95,0)
    INDIAN_RED1         = "indian_red1"          # #ff5f87  rgb(255,95,135)
    HOT_PINK            = "hot_pink"             # #ff5fd7  rgb(255,95,215)
    MEDIUM_ORCHID1      = "medium_orchid1"       # #ff5fff  rgb(255,95,255)
    DARK_ORANGE         = "dark_orange"          # #ff8700  rgb(255,135,0)
    SALMON1             = "salmon1"              # #ff875f  rgb(255,135,95)
    LIGHT_CORAL         = "light_coral"          # #ff8787  rgb(255,135,135)
    PALE_VIOLET_RED1    = "pale_violet_red1"     # #ff87af  rgb(255,135,175)
    ORCHID2             = "orchid2"              # #ff87d7  rgb(255,135,215)
    ORCHID1             = "orchid1"              # #ff87ff  rgb(255,135,255)
    ORANGE1             = "orange1"              # #ffaf00  rgb(255,175,0)
    SANDY_BROWN         = "sandy_brown"          # #ffaf5f  rgb(255,175,95)
    LIGHT_SALMON1       = "light_salmon1"        # #ffaf87  rgb(255,175,135)
    LIGHT_PINK1         = "light_pink1"          # #ffafaf  rgb(255,175,175)
    PINK1               = "pink1"                # #ffafd7  rgb(255,175,215)
    PLUM1               = "plum1"                # #ffafff  rgb(255,175,255)
    GOLD1               = "gold1"                # #ffd700  rgb(255,215,0)
    LIGHT_GOLDENROD2    = "light_goldenrod2"     # #ffd787  rgb(255,215,135)
    NAVAJO_WHITE1       = "navajo_white1"        # #ffd7af  rgb(255,215,175)
    MISTY_ROSE1         = "misty_rose1"          # #ffd7d7  rgb(255,215,215)
    THISTLE1            = "thistle1"             # #ffd7ff  rgb(255,215,255)
    YELLOW1             = "yellow1"              # #ffff00  rgb(255,255,0)
    LIGHT_GOLDENROD1    = "light_goldenrod1"     # #ffff5f  rgb(255,255,95)
    KHAKI1              = "khaki1"               # #ffff87  rgb(255,255,135)
    WHEAT1              = "wheat1"               # #ffffaf  rgb(255,255,175)
    CORNSILK1           = "cornsilk1"            # #ffffd7  rgb(255,255,215)
    GREY100             = "grey100"              # #ffffff  rgb(255,255,255)
    GREY3               = "grey3"                # #080808  rgb(8,8,8)
    GREY7               = "grey7"                # #121212  rgb(18,18,18)
    GREY11              = "grey11"               # #1c1c1c  rgb(28,28,28)
    GREY15              = "grey15"               # #262626  rgb(38,38,38)
    GREY19              = "grey19"               # #303030  rgb(48,48,48)
    GREY23              = "grey23"               # #3a3a3a  rgb(58,58,58)
    GREY27              = "grey27"               # #444444  rgb(68,68,68)
    GREY30              = "grey30"               # #4e4e4e  rgb(78,78,78)
    GREY35              = "grey35"               # #585858  rgb(88,88,88)
    GREY39              = "grey39"               # #626262  rgb(98,98,98)
    GREY42              = "grey42"               # #6c6c6c  rgb(108,108,108)
    GREY46              = "grey46"               # #767676  rgb(118,118,118)
    GREY50              = "grey50"               # #808080  rgb(128,128,128)
    GREY54              = "grey54"               # #8a8a8a  rgb(138,138,138)
    GREY58              = "grey58"               # #949494  rgb(148,148,148)
    GREY62              = "grey62"               # #9e9e9e  rgb(158,158,158)
    GREY66              = "grey66"               # #a8a8a8  rgb(168,168,168)
    GREY70              = "grey70"               # #b2b2b2  rgb(178,178,178)
    GREY74              = "grey74"               # #bcbcbc  rgb(188,188,188)
    GREY78              = "grey78"               # #c6c6c6  rgb(198,198,198)
    GREY82              = "grey82"               # #d0d0d0  rgb(208,208,208)
    GREY85              = "grey85"               # #dadada  rgb(218,218,218)
    GREY89              = "grey89"               # #e4e4e4  rgb(228,228,228)
    GREY93              = "grey93"               # #eeeeee  rgb(238,238,238)


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from rich import print
    from rich.panel import Panel

    #! label with border 
    print(Panel("Hello, [red]World!"))
    print(":red_heart-emoji:")
    pause()
    clear()

    #! colored box
    from rich.padding import Padding
    test = Padding("Hello", (2, 4), style="on blue", expand=False)
    print(test)
    pause()
    clear()

    #! group things together
    from rich import print
    from rich.console import Group
    from rich.panel import Panel

    panel_group = Group(
        Panel("Hello", style="on blue"),
        Panel("World", style="on red"),
    )
    print(Panel(panel_group))

    pause()
    clear()
