# CryptoTrack Portfolio App

CryptoTrack is a Django-based application that enables users to track cryptocurrency prices, manage a personalized
watchlist, and monitor unrealized profit/loss for their portfolio by recording buy and sell operations. The app is
powered by the CoinGecko API.

## Features

- User authentication (registration, login, logout)
- View a list of cryptocurrencies with current prices
- Search for cryptocurrencies by name or symbol
- Add or remove cryptocurrencies from a watchlist
- Record buy and sell operations to track your portfolio
- View useful metrics such as unrealized profit/loss
- Admin panel to manage users, coins, and operations
- Disable coins from appearing in the app (useful for delisted coins)
- Caching to reduce requests to the CoinGecko API
- Background job to keep the database updated with the latest coins from CoinGecko

## Tech Stack

- Django
- PostgreSQL
- Bootstrap 5
- CoinGecko API
- APScheduler for background jobs

## Installation

1. Create a virtual environment, activate it, and install dependencies:

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   pip install -r requirements.txt
   ```

2. Create postgresql role and database:

   - Create crypto_track role

   - Create crypto_track database owned by crypto_track role

   - Grant connect privilege on postgres database to crypto_track role in order to execute tests

The configuration expects a local connection type with trust authentication for simplicity. Adjust your `pg_hba.conf`
file as needed.

2. Apply migrations:

   ```bash
   python manage.py migrate
   ```

3. Initialize the cache database:

   ```bash
   python manage.py createcachetable
   ```

4. To access the admin panel, create a superuser:

   ```bash
   python manage.py createsuperuser
   ```

5. Set environment variables:

   - `COINGECKO_KEY`: API key for CoinGecko

   The project supports `.env` files. You can create a `.env` file in the root directory and add the variables.

6. Before starting the server, fetch the coins from the CoinGecko API and populate the database:

   ```bash
   python manage.py runapscheduler --run-now
   ```

   You must run this at least once before starting the server. This custom command starts an APScheduler instance that
   fetches the listed coins from CoinGecko every two hours to keep the database updated. The `--run-now` flag triggers
   the job immediately.

The project uses SQLite as the default database, so no additional setup is required.

## Running the Server

To start the development server, run:

```bash
python manage.py runserver
```

Then open your browser and navigate to `http://localhost:8000`.

## Running Tests

To execute the test suite, run:

```bash
python manage.py test
```
