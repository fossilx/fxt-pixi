#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)


#!================================================================================(80)
#! imports
#!--------------------------------------------------------------------------------(80)
import sys
import os

def is_notebook():
    """ Check if IPython is loaded and if the shell is ZMQInteractiveShell (Jupyter)
    """

    if('IPython' in sys.modules):
        from IPython import get_ipython #type: ignore
        ipython = get_ipython().__class__.__name__

        if(ipython is not None):
            if(ipython == 'ZMQInteractiveShell'):
                #! case: Jupyter Notebook or JupyterLab
                return True
            elif(ipython == 'TerminalInteractiveShell'):
                #! case: IPython terminal
                return False
    
    #! case: standard Python interpreter or other type of shell
    return False
#



#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from rich import print
    from IPython import get_ipython #type: ignore

    print(
        f"is_notebook() = {is_notebook()}"

        #also set within jupyter, but it is also set by some IDEs (ie Spyder), 
        # so it is not a reliable indicator of being in a jupyter notebook
        f"\nJPY_PARENT_PID = {os.getenv('JPY_PARENT_PID')}" 
        f"\nJUPYTER_SERVER_ROOT = {os.getenv('JUPYTER_SERVER_ROOT')}"
    )

    

    #print(os.getenv("JPY_PARENT_PID"))

