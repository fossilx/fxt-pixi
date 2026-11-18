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

from pydantic import SecretStr

#local
from .settings import get_secrets




 


#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
import logging
logger = logging.getLogger(__name__)


TELEGRAM_API = "https://api.telegram.org"
MAX_MESSAGE_LEN = 4096  # Telegram's limit for a single message
 
 
class NotifyError(RuntimeError):
    """ Raised when a notification can't be delivered.
        The message never contains the bot token.
    """
 



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
#! main
#!--------------------------------------------------------------------------------(80)
class Notifier:
    """ Sends messages to a Telegram chat through a bot.
 
        Gets its token and chat id injected (see fxt.services.get_notifier);
        it never reads the .env file itself.
 
        - send():     raises NotifyError on failure
        - try_send(): logs a warning and returns False on failure, so a failed
                      alert can't crash a long-running job
    """
 
    def __init__(
        self,
        token: SecretStr,
        user_id: int,
        *,
        parse_mode: str | None = "Markdown",
        timeout: float = 10.0,
    ):
        if not token.get_secret_value():
            raise ValueError("Telegram token is empty")
        
        self._token = token
        self.user_id = user_id
        self.parse_mode = parse_mode
        self.timeout = timeout
        self._session = requests.Session()
    #
 
    def __repr__(self) -> str:
        return f"Notifier(user_id={self.user_id}, parse_mode={self.parse_mode!r})"
    #
 
    #~======================================================================(70)
    #~ api
    #~----------------------------------------------------------------------(70)
    def send(self, message: str) -> None:
        """ Send a message. Raises NotifyError if it can't be delivered. """
        text = message
        if len(text) > MAX_MESSAGE_LEN:
            text = text[: MAX_MESSAGE_LEN - 1] + "…"
 
        resp = self._post(text, self.parse_mode)
 
        # Legacy Markdown rejects unbalanced * _ ` [ (e.g. "EUR_USD" or a file path).
        # Rather than lose the alert, resend it as plain text.
        if resp.status_code == 400 and self.parse_mode and "can't parse entities" in resp.text:
            logger.warning("Telegram couldn't parse the message as %s; resending as plain text", self.parse_mode)
            resp = self._post(text, None)
 
        if not resp.ok:
            # resp.text is Telegram's JSON error description; it doesn't include the URL/token
            raise NotifyError(f"Telegram API error {resp.status_code}: {resp.text[:200]}")
    #
 
    def try_send(self, message: str) -> bool:
        """ Like send(), but logs failures instead of raising. Returns True if sent. 
        """
        try:
            self.send(message)
            return True
        except NotifyError as e:
            logger.warning("Notification not sent: %s", e)
            return False
    #
 
    #~======================================================================(70)
    #~ internals
    #~----------------------------------------------------------------------(70)
    def _post(self, text: str, parse_mode: str | None) -> requests.Response:
        payload: dict[str, object] = {"chat_id": self.user_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
 
        url = f"{TELEGRAM_API}/bot{self._token.get_secret_value()}/sendMessage"
        try:
            return self._session.post(url, json=payload, timeout=self.timeout)
        except requests.RequestException as e:
            # requests puts the full URL (including the token) in its exception
            # messages; `from None` keeps it out of tracebacks and logs.
            raise NotifyError(f"Couldn't reach Telegram ({type(e).__name__})") from None
    #
#-



#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80) 
if __name__ == '__main__':
    from datetime import datetime, date, UTC
    from rich import print
    from rich.panel import Panel

    notifier = Notifier(
        token=get_secrets().TELEGRAM_TOKEN,
        user_id=get_secrets().TELEGRAM_USERID
    )


    now = datetime.now()
    formatted = now.strftime("%b %d, %I:%M %p").replace(" 0", " ")
    msg = f"⚠️ *fxt.notify* [[{formatted}]]: \n\nthis message should appear in telegram."

    
    print(Panel(
        msg,
        title="[orchid2]notify-msg[/]", title_align="left"
    ))

    notifier.send(msg)

    # send_telegram_alert(msg)
