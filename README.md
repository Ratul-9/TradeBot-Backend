# IEM Trade Bot Project

This project is a **virtual stock trading platform** built with Django, Django REST Framework, Celery, and PostgreSQL. It provides APIs for user management, trading stocks (buy/sell/stop-loss/limit orders), maintaining virtual portfolios, and supports asynchronous order execution via real market data integrations.

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Database Setup and Migrations](#database-setup-and-migrations)
- [Running the Application](#running-the-application)
- [Running Celery](#running-celery)
- [API Usage](#api-usage)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Features

- User registration, JWT authentication, and staff login.
- Virtual balance management.
- Buy and sell stocks with market, limit, or stop-loss orders.
- Pending order management and automatic execution via Celery.
- Portfolio and transaction history tracking.
- Modular Django apps: `users`, `stocks`, `transactions`.

---

## Tech Stack

- **Backend:** Django 5.1.7, Django REST Framework, Celery
- **Database:** PostgreSQL
- **Task Queue:** Celery with Redis (as default broker)
- **API Auth:** JWT (`djangorestframework-simplejwt`)
- **Market Data:** Alpha Vantage API (via API key)
- **Others:** CORS, dotenv for configuration

---

## Prerequisites

- Python 3.10+ recommended
- PostgreSQL (running locally or remotely)
- Redis (for Celery task queuing)
- [Alpha Vantage](https://www.alphavantage.co/) API Key (free signup)
- Git

---

## Installation

1. **Clone the repository**
    ```sh
    git clone https://github.com/Ratul-9/iemtradebot_project.git
    cd iemtradebot_project
    ```

2. **Create a virtual environment**
    ```sh
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3. **Install dependencies**
    ```sh
    pip install -r requirements.txt
    ```

---

## Configuration

1. **Setup environment variables**

    Create a `.env` file in the root directory with the following content:

    ```env
    ALPHA_VANTAGE_API_KEY=your_alpha_vantage_api_key_here
    ```

    (You can add DB credentials too, but they're set by default in `backend/settings.py`.)

2. **Edit database settings**

    By default, settings in `backend/settings.py`:

    ```python
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': 'your_db_name',
            'USER': 'your_user_name',
            'PASSWORD': 'your_password',
            'HOST': 'localhost',
            'PORT': '5432',
        }
    }
    ```


3. **Redis Setup (for Celery)**

    - Install Redis:
      - On macOS: `brew install redis`
      - On Ubuntu: `sudo apt-get install redis-server`
      - On Windows: [Follow Redis for Windows guide](https://redis.io/docs/latest/operate/installation/install-redis-on-windows/)
    - Start Redis server:
      ```sh
      redis-server
      ```

---

## Database Setup and Migrations

1. **Apply migrations**

    ```sh
    python manage.py makemigrations
    python manage.py migrate
    ```

2. **Create a superuser (for Django admin access)**

    ```sh
    python manage.py createsuperuser
    ```

---

## Running the Application

1. **Start the Django development server**

    ```sh
    python manage.py runserver
    ```

    The API is now accessible at [http://localhost:8000](http://127.0.0.0.0.1:8000).

2. **Access the Django Admin**

    Go to [http://127.0.0.0.1.0:8000/admin/](http://127.0.0.0.0.1:800/admin/) and log in with your superuser credentials.

---

## Running Celery

Celery is used to execute pending/limit/stop-loss orders asynchronously.

**Start the Celery worker:**

```sh
celery -A backend worker --loglevel=info
```

If you want to run periodic tasks (like checking pending orders), you may also need:

```sh
celery -A backend beat --loglevel=info
```

---

## API Usage

### Base API URLs

- Users: `/api/users/`
- Stocks: `/api/stocks/`
- Transactions: `/api/transactions/`

### Authentication

- Obtain JWT tokens via `/api/users/login/` (POST with username and password).
- Use the returned access token as `Authorization: Bearer <token>` in subsequent requests.

### Example Endpoints

- **Buy Stock:** `POST /api/transactions/buy_stock/`
- **Sell Stock:** `POST /api/transactions/sell_stock/`
- **Portfolio:** `GET /api/transactions/portfolio/`
- **Transaction History:** `GET /api/transactions/transaction_history/`
- **Pending Orders:** `GET /api/transactions/pending_orders/`
- **User Balance:** `GET /api/users/balance/`

> See the code in `/transactions/views.py` and `/users/views.py` for full endpoint details and request/response formats.

---

## Development

- **Add new apps:** `python manage.py startapp <appname>`
- **Run tests:** `python manage.py test`
- **Linting:** Use tools like `flake8` or `black` as needed.

---

## Troubleshooting

- **Database connection errors:** Ensure PostgreSQL is running, credentials are correct, and database exists.
- **Redis errors:** Ensure Redis server is running.
- **Celery not processing orders:** Check the Celery worker log for errors, ensure both Django and Celery are running.
- **API Key errors:** Make sure you have a valid Alpha Vantage API key in your `.env` file.

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

## Credits

- Developed by [Ratul-9](https://github.com/Ratul-9) and contributors.

---

**For any issues, please open an issue on the GitHub repository.**
