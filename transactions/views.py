from django.shortcuts import render
from django.db import models
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from django.contrib.auth import get_user_model
from .models import Transaction, Portfolio, PendingOrder
from users.models import CustomUser
from .serializers import TransactionSerializer, PortfolioSerializer, PendingOrderSerializer
from decimal import Decimal

User = get_user_model()

@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def buy_stock(request):
    try:
        user = request.user
        data = request.data
        symbol = data.get("symbol")
        quantity = int(data.get("quantity", 0))
        price_per_stock = Decimal(data.get("price_per_stock", 0))
        buy_type = data.get("buy_type", "current")
        stop_loss_price = data.get("stop_loss_price")  

        if not symbol or quantity <= 0 or price_per_stock <= 0:
            return Response({"error": "Invalid input"}, status=status.HTTP_400_BAD_REQUEST)
    
        total_price = quantity * price_per_stock

        if user.virtual_balance < total_price:
            return Response({"error": "Insufficient Funds"}, status=status.HTTP_400_BAD_REQUEST)

        if buy_type == "current":
            user.virtual_balance -= total_price
            user.save()

            transaction = Transaction.objects.create(
                user=user,
                symbol=symbol,
                quantity=quantity,
                price_per_stock=price_per_stock,
                total_price=total_price,
                transaction_type="BUY",
            )
            serializer = TransactionSerializer(transaction)

            portfolio, created = Portfolio.objects.get_or_create(user=user, symbol=symbol)

            if created:
                portfolio.quantity = quantity
                portfolio.average_price = price_per_stock
            else:
                total_shares = portfolio.quantity + quantity
                portfolio.average_price = ((portfolio.quantity * portfolio.average_price) + total_price) / total_shares
                portfolio.quantity = total_shares

            portfolio.save()

            if stop_loss_price and Decimal(stop_loss_price) > 0:
                PendingOrder.objects.create(
                    user=user,
                    symbol=symbol,
                    quantity=quantity,
                    stop_loss_price=Decimal(stop_loss_price), 
                    status="PENDING",
                    order_type="SELL"  
                )

            return Response({"message": "Stock purchased successfully", "transaction": serializer.data}, status=status.HTTP_201_CREATED)

        else:
            pending_order = PendingOrder.objects.create(
                user=user,
                symbol=symbol,
                quantity=quantity,
                target_price=price_per_stock,
                status="PENDING",
                order_type="BUY"
            )
            serializer = PendingOrderSerializer(pending_order)
            return Response({"message": "Order placed and waiting for target price", "pending_order": serializer.data}, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def pending_orders_view(request):
    user = request.user
    pending_orders = PendingOrder.objects.filter(user=user, status="PENDING").order_by("-created_at")
    serializer = PendingOrderSerializer(pending_orders, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)

@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def sell_stock(request):
    user = request.user
    data = request.data

    symbol = data.get("symbol")
    quantity = int(data.get("quantity"))
    price_per_stock = Decimal(data.get("price_per_stock"))
    sell_type = data.get("sell_type", "current")
    stop_loss_price = data.get("stop_loss_price") 

    if not symbol or quantity <= 0 or price_per_stock <= 0:
        return Response({"error": "Invalid input"}, status=status.HTTP_400_BAD_REQUEST)
    
    portfolio_entry = Portfolio.objects.filter(user=user, symbol=symbol).first()

    if not portfolio_entry or portfolio_entry.quantity < quantity:
        return Response({"error": "Not enough stock to sell"}, status=status.HTTP_400_BAD_REQUEST)
    
    total_price = quantity * price_per_stock

    if sell_type == "current":
        portfolio_entry.quantity -= quantity
        if portfolio_entry.quantity == 0:
            portfolio_entry.delete()
        else:
            portfolio_entry.save()

        user.virtual_balance += total_price
        user.save()

        transaction = Transaction.objects.create(
            user=user,
            symbol=symbol,
            quantity=quantity,
            price_per_stock=price_per_stock,
            total_price=total_price,
            transaction_type="SELL",
        )

        return Response({"message": "Stock sold successfully", "transaction_id": transaction.id}, status=status.HTTP_201_CREATED)
    else:
        pending_order = PendingOrder.objects.create(
            user=user,
            symbol=symbol,
            quantity=quantity,
            target_price=price_per_stock,
            stop_loss_price=stop_loss_price,  
            status="PENDING",
            order_type="SELL"
        )
        serializer = PendingOrderSerializer(pending_order)
        return Response({"message": "Sell order placed and waiting for target price", "pending_order": serializer.data}, status=status.HTTP_201_CREATED)

@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def transaction_history(request):
    user = request.user
    transactions = Transaction.objects.filter(user=user).order_by("-created_at")
    transaction_list = [
        {
            "symbol": t.symbol,
            "quantity": t.quantity,
            "price_per_stock": str(t.price_per_stock),
            "total_price": str(t.total_price),
            "transaction_type": t.transaction_type,
            "created_at": t.created_at,
        }
        for t in transactions
    ]

    return Response(transaction_list, status=status.HTTP_200_OK)

@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def portfolio_view(request):
    user = request.user
    portfolio = Portfolio.objects.filter(user=user)
    serializer = PortfolioSerializer(portfolio, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def order_book_view(request):
    user = request.user
    
    # Fetch executed transactions (both buy and sell)
    executed_orders = Transaction.objects.filter(user=user).order_by("-created_at")
    executed_serializer = TransactionSerializer(executed_orders, many=True)

    # Fetch pending orders (buy and sell orders that are not executed yet)
    pending_orders = PendingOrder.objects.filter(user=user, status__iexact="PENDING").order_by("-created_at")
    pending_serializer = PendingOrderSerializer(pending_orders, many=True)

    # Fetch closed orders (only sell transactions)
    closed_orders = Transaction.objects.filter(user=user, transaction_type="SELL").order_by("-created_at")
    closed_serializer = TransactionSerializer(closed_orders, many=True)

    return Response({
        "executed_orders": executed_serializer.data,
        "pending_orders": pending_serializer.data,
        "closed_orders": closed_serializer.data
    }, status=status.HTTP_200_OK)