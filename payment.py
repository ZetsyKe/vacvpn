import os
import uuid
import yookassa
from dotenv import load_dotenv


yookassa.Configuration.account_id = os.environ.get("SHOP_ID")
yookassa.Configuration.secret_key = os.environ.get("API_KEY")


def create_payment(amount, return_url):
    idempotence_key = str(uuid.uuid4())
    payment = yookassa.Payment.create({
        "amount": {
            "value": amount,
            "currency": "RUB"
        },
        "confirmation": {
            "type": "redirect",
            "return_url": return_url
        },
        "capture": True,
        "description": "Пополнение баланса"
    }, idempotence_key)

    return payment.confirmation.confirmation_url
