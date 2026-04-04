from transbank.webpay.webpay_plus.transaction import Transaction
from transbank.common.integration_type import IntegrationType

# Crear transacción en modo TEST
tx = Transaction(integration_type=IntegrationType.TEST)

resp = tx.create(
    buy_order="ORDER123",
    session_id="SESSION123",
    amount=1000,
    return_url="https://www.google.cl"
)

print(resp)
