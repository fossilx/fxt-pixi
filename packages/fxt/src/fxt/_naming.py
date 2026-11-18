#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
# stop pylance from being annoying by adding this to end of line:  # type: ignore
# https://rich.readthedocs.io/en/stable/appendix/colors.html




PREFIX = "fxt"
def attr(name: str) -> str:
    """ Little utility to generate custom attributes in a consistent fashion.
    """
    return f"_{PREFIX}_{name}"
#


__all__ = [
    'PREFIX',
    'attr',
]