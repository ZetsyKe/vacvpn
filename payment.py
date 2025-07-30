import os
import uuid
import yookassa
from dotenv import load_dotenv

load_dotenv(dotenv_path="backend/key.env")

yookassa.Configuration.account_id = os.getenv("SHOP_ID")
yookassa.Configuration.secret_key = os.getenv("API_KEY")


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