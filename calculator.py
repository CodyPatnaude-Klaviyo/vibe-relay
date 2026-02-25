"""Calculator module with basic arithmetic operations."""


def add(a: int | float, b: int | float) -> int | float:
    """Return the sum of two numbers.

    Args:
        a: First number
        b: Second number

    Returns:
        The sum of a and b
    """
    return a + b


def subtract(a: int | float, b: int | float) -> int | float:
    """Return the difference of two numbers (a - b).

    Args:
        a: First number
        b: Second number

    Returns:
        The difference a - b
    """
    return a - b


def multiply(a: int | float, b: int | float) -> int | float:
    """Return the product of two numbers.

    Args:
        a: First number
        b: Second number

    Returns:
        The product of a and b
    """
    return a * b


def divide(a: int | float, b: int | float) -> float:
    """Return the quotient of two numbers (a / b).

    Args:
        a: Dividend
        b: Divisor

    Returns:
        The quotient a / b as a float

    Raises:
        ZeroDivisionError: If b is 0
    """
    if b == 0:
        raise ZeroDivisionError("Cannot divide by zero")
    return a / b
