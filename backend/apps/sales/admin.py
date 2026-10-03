from django.contrib import admin  # noqa: F401

# Sem admin de propósito: a venda tem efeitos no rebanho, e só a tela os desfaz
# e reaplica na mesma transação (como `purchases` e `costs`).
