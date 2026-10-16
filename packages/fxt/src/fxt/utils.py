#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)


#!================================================================================(80)
#! imports
#!--------------------------------------------------------------------------------(80)
import sys

def is_notebook():
    """ Check if IPython is loaded and if the shell is ZMQInteractiveShell (Jupyter)
        
    """

    if 'IPython' in sys.modules:
        #from IPython import get_ipython
        from IPython.core.getipython import get_ipython
        shell = get_ipython().__class__.__name__
        if shell == 'ZMQInteractiveShell':
            return True   # Jupyter Notebook or JupyterLab
        elif shell == 'TerminalInteractiveShell':
            return False  # IPython terminal
    return False          # Standard Python script / CLI
#



#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
