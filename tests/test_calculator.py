"""Tests for calculator module."""

import pytest


def test_add_two_integers():
    """Test adding two integers."""
    from calculator import add

    result = add(2, 3)

    assert result == 5


def test_add_two_floats():
    """Test adding two floats."""
    from calculator import add

    result = add(2.5, 3.7)

    assert result == 6.2


def test_subtract_two_integers():
    """Test subtracting two integers."""
    from calculator import subtract

    result = subtract(5, 3)

    assert result == 2


def test_subtract_with_negative_result():
    """Test subtraction resulting in negative number."""
    from calculator import subtract

    result = subtract(3, 5)

    assert result == -2


def test_multiply_two_integers():
    """Test multiplying two integers."""
    from calculator import multiply

    result = multiply(3, 4)

    assert result == 12


def test_multiply_by_zero():
    """Test multiplying by zero."""
    from calculator import multiply

    result = multiply(5, 0)

    assert result == 0


def test_divide_two_integers():
    """Test dividing two integers."""
    from calculator import divide

    result = divide(10, 2)

    assert result == 5


def test_divide_returns_float():
    """Test division returns float when not evenly divisible."""
    from calculator import divide

    result = divide(7, 2)

    assert result == 3.5


def test_divide_by_zero_raises_error():
    """Test division by zero raises ZeroDivisionError with clear message."""
    from calculator import divide

    with pytest.raises(ZeroDivisionError, match="Cannot divide by zero"):
        divide(10, 0)
