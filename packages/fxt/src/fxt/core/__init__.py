"""

Files in the core section SHOULD NOT create instances of themselves. They are meant
to be used in other modules.

Anything that needs to use the settings to create a singleton instance of itself 
should have a correspodning function in fxt/services.py

"""