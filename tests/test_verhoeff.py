import random

from vaultproxy.detectors.verhoeff import generate_verhoeff, validate_verhoeff


def test_verhoeff_round_trip():
    random.seed(42)
    for _ in range(50):
        # Generate random 11-digit string starting with 2-9
        first_digit = str(random.randint(2, 9))
        rest_digits = "".join([str(random.randint(0, 9)) for _ in range(10)])
        prefix = first_digit + rest_digits

        check_digit = generate_verhoeff(prefix)
        full_number = prefix + str(check_digit)

        # Validator accepts valid checksum
        assert validate_verhoeff(full_number) is True

        # Validator rejects any single-digit mutation
        for i in range(len(full_number)):
            original_digit = int(full_number[i])
            mutated_digit = (original_digit + random.randint(1, 9)) % 10
            mutated_number = (
                full_number[:i] + str(mutated_digit) + full_number[i + 1 :]
            )
            assert validate_verhoeff(mutated_number) is False


def test_invalid_non_digit_verhoeff():
    assert validate_verhoeff("12345678901a") is False
