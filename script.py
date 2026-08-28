import csv
import os
import secrets
import time
from pathlib import Path

import requests

BASE_URL = "https://api.monnify.com/"

INPUT_FILE = Path("accounts.csv")
OUTPUT_FILE = Path("results.csv")

REQUEST_DELAY = 1.0
MAX_RETRIES = 3
TIMEOUT = 20

MOBILE_PREFIXES = [
    "0701",
    "0703",
    "0704",
    "0705",
    "0706",
    "0707",
    "0708",

    "0802",
    "0803",
    "0804",
    "0805",
    "0806",
    "0807",
    "0808",
    "0809",

    "0810",
    "0811",
    "0812",
    "0813",
    "0814",
    "0815",
    "0816",
    "0817",
    "0818",
    "0819",

    "0901",
    "0902",
    "0903",
    "0904",
    "0905",
    "0906",
    "0907",
    "0908",
    "0909",

    "0911",
    "0912",
    "0913",
    "0915",
    "0916",
]


def generate_mobile_numbers(count):

    if count < 0:
        raise ValueError("count must be zero or greater")

    numbers = set()

    while len(numbers) < count:

        prefix = secrets.choice(MOBILE_PREFIXES)
        suffix = "".join(
            secrets.choice("0123456789")
            for _ in range(7)
        )
        number = prefix + suffix

        if number in numbers:
            print(f"Duplicate skipped: {number}", flush=True)
            continue

        numbers.add(number)
        print(
            f"Generated {len(numbers)}/{count}: {number}",
            flush=True,
        )
        yield number


class MonnifyClient:

    def __init__(self):
        try:
            self.api_key = os.environ["MONNIFY_API_KEY"]
            self.secret_key = os.environ["MONNIFY_SECRET_KEY"]
        except KeyError as exc:
            raise RuntimeError(
                f"Missing environment variable: {exc.args[0]}"
            )

        self.session = requests.Session()
        self.token = None

    # --------------------------------------------------------
    # Authentication
    # --------------------------------------------------------

    def authenticate(self):

        print("Authenticating with Monnify...")

        response = self.session.post(
            f"{BASE_URL}/api/v1/auth/login",
            auth=(
                self.api_key,
                self.secret_key,
            ),
            timeout=TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        if not data.get("requestSuccessful"):
            raise RuntimeError(
                data.get(
                    "responseMessage",
                    "Authentication failed",
                )
            )

        self.token = data["responseBody"]["accessToken"]

        print("Authentication successful.")


    def validate_account(
        self,
        account_number,
        bank_code,
    ):

        if not self.token:
            self.authenticate()

        url = (
            f"{BASE_URL}/api/v2/"
            "disbursements/account/validate"
        )

        params = {
            "accountNumber": account_number,
            "bankCode": bank_code,
        }

        for attempt in range(
            1,
            MAX_RETRIES + 1,
        ):

            try:

                response = self.session.get(
                    url,
                    params=params,
                    headers={
                        "Authorization": (
                            f"Bearer {self.token}"
                        )
                    },
                    timeout=TIMEOUT,
                )

                # ------------------------------------------------
                # Token expired
                # ------------------------------------------------

                if response.status_code == 401:

                    print(
                        "Authentication expired. "
                        "Refreshing token..."
                    )

                    self.authenticate()
                    continue

                response.raise_for_status()

                data = response.json()

                # ------------------------------------------------
                # Successful validation
                # ------------------------------------------------

                if data.get("requestSuccessful"):

                    return {
                        "status": "validated",
                        "account_number": account_number,
                        "bank_code": bank_code,
                        "message": data.get(
                            "responseMessage",
                            "Success",
                        ),
                    }

                # ------------------------------------------------
                # API rejected the account
                # ------------------------------------------------

                return {
                    "status": "failed",
                    "account_number": account_number,
                    "bank_code": bank_code,
                    "message": data.get(
                        "responseMessage",
                        "Validation failed",
                    ),
                }

            except requests.RequestException as exc:

                print(
                    f"Request failed "
                    f"(attempt {attempt}/{MAX_RETRIES}): "
                    f"{exc}"
                )

                if attempt == MAX_RETRIES:

                    return {
                        "status": "error",
                        "account_number": account_number,
                        "bank_code": bank_code,
                        "message": str(exc),
                    }

                # Exponential backoff:
                #
                # attempt 1 → 1 second
                # attempt 2 → 2 seconds
                # attempt 3 → 4 seconds

                time.sleep(2 ** (attempt - 1))


# ============================================================
# INPUT
# ============================================================

def load_accounts():

    if not INPUT_FILE.exists():

        raise FileNotFoundError(
            f"Input file not found: {INPUT_FILE}"
        )

    with INPUT_FILE.open(
        newline="",
        encoding="utf-8",
    ) as file:

        reader = csv.DictReader(file)

        required_columns = {
            "account_number",
            "bank_code",
        }

        actual_columns = set(
            reader.fieldnames or []
        )

        missing = (
            required_columns
            - actual_columns
        )

        if missing:

            raise ValueError(
                "Missing CSV columns: "
                + ", ".join(sorted(missing))
            )

        for row in reader:

            account_number = (
                row["account_number"]
                .strip()
            )

            bank_code = (
                row["bank_code"]
                .strip()
            )

            if not account_number:
                continue

            if not bank_code:
                continue

            yield (
                account_number,
                bank_code,
            )


# ============================================================
# CHECKPOINTING
# ============================================================

def load_processed():

    processed = set()

    if not OUTPUT_FILE.exists():
        return processed

    with OUTPUT_FILE.open(
        newline="",
        encoding="utf-8",
    ) as file:

        reader = csv.DictReader(file)

        for row in reader:

            account = row.get(
                "account_number",
                "",
            )

            bank_code = row.get(
                "bank_code",
                "",
            )

            if account and bank_code:

                processed.add(
                    (
                        account,
                        bank_code,
                    )
                )

    return processed


# ============================================================
# SAVE RESULT
# ============================================================

def save_result(result):

    file_exists = OUTPUT_FILE.exists()

    fields = [
        "status",
        "account_number",
        "bank_code",
        "message",
    ]

    with OUTPUT_FILE.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fields,
        )

        if not file_exists:
            writer.writeheader()

        writer.writerow({
            field: result.get(
                field,
                "",
            )
            for field in fields
        })

        # Make sure the result is physically written
        # before moving to the next account.

        file.flush()


# ============================================================
# MAIN WORKER
# ============================================================

def main():

    print("=" * 60)
    print("Monnify Account Validation Experiment")
    print("=" * 60)

    client = MonnifyClient()

    processed = load_processed()

    accounts = list(
        load_accounts()
    )

    print(
        f"Accounts loaded: {len(accounts)}"
    )

    print(
        f"Already processed: {len(processed)}"
    )

    remaining = [
        item
        for item in accounts
        if item not in processed
    ]

    print(
        f"Remaining: {len(remaining)}"
    )

    print()

    if not remaining:

        print("Nothing left to process.")
        return

    validated = 0
    failed = 0
    errors = 0

    # --------------------------------------------------------
    # Process accounts
    # --------------------------------------------------------

    for index, (
        account_number,
        bank_code,
    ) in enumerate(
        remaining,
        start=1,
    ):

        print(
            f"[{index}/{len(remaining)}] "
            f"Validating account..."
        )

        result = client.validate_account(
            account_number,
            bank_code,
        )

        save_result(result)

        status = result["status"]

        if status == "validated":
            validated += 1

        elif status == "failed":
            failed += 1

        else:
            errors += 1

        print(
            f"    Result: {status}"
        )

        # Don't hammer the API.

        time.sleep(
            REQUEST_DELAY
        )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print()
    print("=" * 60)
    print("Experiment complete")
    print("=" * 60)

    print(
        f"Validated : {validated}"
    )

    print(
        f"Failed    : {failed}"
    )

    print(
        f"Errors    : {errors}"
    )

    print(
        f"Results   : {OUTPUT_FILE}"
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()