from html import escape
from urllib.parse import quote

import httpx

from app.config import settings


GRAPH_SCOPE = "https://graph.microsoft.com/.default"


def email_is_configured() -> bool:
    return bool(
        settings.EMAIL_NOTIFICATIONS_ENABLED
        and settings.AZURE_TENANT_ID
        and settings.AZURE_CLIENT_ID
        and settings.AZURE_CLIENT_SECRET
        and settings.EMAIL_SENDER
    )


async def get_graph_access_token() -> str:
    token_url = (
        f"https://login.microsoftonline.com/"
        f"{settings.AZURE_TENANT_ID}/oauth2/v2.0/token"
    )

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            token_url,
            data={
                "client_id": settings.AZURE_CLIENT_ID,
                "client_secret": settings.AZURE_CLIENT_SECRET,
                "scope": GRAPH_SCOPE,
                "grant_type": "client_credentials",
            },
        )

        response.raise_for_status()
        token_data = response.json()

    access_token = token_data.get("access_token")

    if not access_token:
        raise RuntimeError(
            "Microsoft Graph non ha restituito un access token"
        )

    return access_token


async def send_action_plan_mention_email(
    recipient_email: str,
    recipient_name: str,
    author_name: str,
    action_plan_id: str,
    action_plan_number: str,
    action_plan_title: str,
    comment_text: str,
) -> dict:
    if not settings.EMAIL_NOTIFICATIONS_ENABLED:
        return {
            "status": "disabled",
            "detail": "Notifiche email disattivate",
        }

    if not email_is_configured():
        return {
            "status": "not_configured",
            "detail": "Configurazione Microsoft Graph incompleta",
        }

    if not recipient_email:
        return {
            "status": "not_available",
            "detail": "Indirizzo email destinatario non disponibile",
        }

    access_token = await get_graph_access_token()

    frontend_url = settings.FRONTEND_URL.rstrip("/")
    action_url = (
        f"{frontend_url}/action-plan?"
        f"open={quote(action_plan_id)}"
    )

    safe_recipient_name = escape(
        recipient_name or recipient_email
    )
    safe_author_name = escape(author_name or "Un utente")
    safe_number = escape(
        action_plan_number or "Action Plan"
    )
    safe_title = escape(
        action_plan_title or "Senza titolo"
    )
    safe_comment = escape(comment_text).replace(
        "\n",
        "<br>",
    )

    html_content = f"""
    <html>
      <body style="font-family:Arial,sans-serif;color:#2f2926;line-height:1.5">
        <div style="max-width:640px;margin:0 auto;padding:24px">
          <h2 style="margin:0 0 16px;color:#5b3517">
            Sei stato menzionato in un Action Plan
          </h2>

          <p>Ciao {safe_recipient_name},</p>

          <p>
            <strong>{safe_author_name}</strong> ti ha menzionato
            in un commento.
          </p>

          <div style="background:#f7f4ef;border-left:4px solid #9b6a1d;padding:16px;margin:20px 0">
            <div style="font-size:13px;color:#6b625c">
              {safe_number}
            </div>
            <div style="font-size:17px;font-weight:bold;margin-top:4px">
              {safe_title}
            </div>
          </div>

          <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin:20px 0">
            {safe_comment}
          </div>

          <p style="margin-top:24px">
            {action_url}
              Apri Action Plan
            </a>
          </p>

          <p style="font-size:12px;color:#8a817b;margin-top:28px">
            Messaggio automatico generato da LPW System.
          </p>
        </div>
      </body>
    </html>
    """

    sender = quote(settings.EMAIL_SENDER)
    send_url = (
        f"https://graph.microsoft.com/v1.0/"
        f"users/{sender}/sendMail"
    )

    payload = {
        "message": {
            "subject": (
                f"Menzione in {action_plan_number or 'Action Plan'}"
            ),
            "body": {
                "contentType": "HTML",
                "content": html_content,
            },
            "toRecipients": [
                {
                    "emailAddress": {
                        "address": recipient_email,
                    }
                }
            ],
        },
        "saveToSentItems": True,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            send_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if response.status_code != 202:
        raise RuntimeError(
            f"Microsoft Graph {response.status_code}: "
            f"{response.text[:500]}"
        )

    return {
        "status": "sent",
        "detail": "Email accettata da Microsoft Graph",
    }
