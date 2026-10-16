#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

'''
Two approaches based on: https://share.gemini.google/pPJPbtZhWYCN

- Use ntfy.sh
  - i think you can self-host the server (it's open source) if you want privacy
  - i think you can use their service for free without signing up, 
    you just broadcast on a certain "topic"
    ...
    and you "subscribe" to that "topic" on your phone
  - the phone app is also free (on googleplay, fdroid, etc)

  
- use something like telegram
  - you signup if needed via phone
  - you then create a bot?
    i'm not 100% sure how telegram bots work
'''


#!================================================================================(80)
#! imports
#!--------------------------------------------------------------------------------(80)
import requests

#local
from fxt.settings import get_secrets


#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
def send_telegram_alert(message):
    """ Sends a message to the telegram bot specified in the .env file. 

        This requires a telegram bot token and a user id to be set in the .env file.
    """
    token = get_secrets().TELEGRAM_TOKEN.get_secret_value()
    chat_id = get_secrets().TELEGRAM_USERID

    if(not token) or (not chat_id):
        raise RuntimeError("TELEGRAM_TOKEN or TELEGRAM_USERID not set in .env file. Cannot send alert.")
        #return


    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown" # Allows you to use *bold* or `code` formatting
    }
    
    requests.post(url, json=payload)
#


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80) 
if __name__ == '__main__':
    # Trigger the alert
    msg = "⚠️ *fxt.notify*: this message should appear in telegram."
    print(f"Trying to send: {msg}")
    send_telegram_alert(msg)
