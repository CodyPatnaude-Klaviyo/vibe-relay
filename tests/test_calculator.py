"""Comprehensive unit tests for the calculator module."""

import pytest

from calculator import add, divide, multiply, subtract


class TestAdd:
    """Test cases for the add function."""

    def test_add_positive_numbers(self):
        """Test adding two positive numbers."""
        assert add(5, 3) == 8
        assert add(100, 50) == 150

    def test_add_negative_numbers(self):
        """Test adding negative numbers."""
        assert add(-5, -3) == -8
        assert add(-10, -20) == -30
        assert add(-5, 3) == -2

    def test_add_with_zero(self):
        """Test adding with zero."""
        assert add(0, 0) == 0
        assert add(5, 0) == 5
        assert add(0, 10) == 10

    def test_add_floats(self):
        """Test adding floating point numbers."""
        assert add(2.5, 3.7) == pytest.approx(6.2)
        assert add(0.1, 0.2) == pytest.approx(0.3)
        assert add(-1.5, 2.5) == pytest.approx(1.0)


class TestSubtract:
    """Test cases for the subtract function."""

    def test_subtract_positive_result(self):
        """Test subtraction resulting in a positive number."""
        assert subtract(10, 5) == 5
        assert subtract(100, 30) == 70
        assert subtract(7, 2) == 5

    def test_subtract_negative_result(self):
        """Test subtraction resulting in a negative number."""
        assert subtract(5, 10) == -5
        assert subtract(20, 50) == -30
        assert subtract(-5, 10) == -15

    def test_subtract_from_zero(self):
        """Test subtracting from zero."""
        assert subtract(0, 5) == -5
        assert subtract(0, 10) == -10
        assert subtract(0, -5) == 5

    def test_subtract_floats(self):
        """Test subtracting floating point numbers."""
        assert subtract(5.5, 2.3) == pytest.approx(3.2)
        assert subtract(10.0, 3.7) == pytest.approx(6.3)


class TestMultiply:
    """Test cases for the multiply function."""

    def test_multiply_positive_numbers(self):
        """Test multiplying positive numbers."""
        assert multiply(5, 3) == 15
        assert multiply(10, 4) == 40
        assert multiply(7, 8) == 56

    def test_multiply_negative_numbers(self):
        """Test multiplying with negative numbers."""
        assert multiply(-5, 3) == -15
        assert multiply(5, -3) == -15
        assert multiply(-5, -3) == 15

    def test_multiply_by_zero(self):
        """Test multiplying by zero."""
        assert multiply(5, 0) == 0
        assert multiply(0, 10) == 0
        assert multiply(0, 0) == 0

    def test_multiply_floats(self):
        """Test multiplying floating point numbers."""
        assert multiply(2.5, 4.0) == pytest.approx(10.0)
        assert multiply(1.5, 3.2) == pytest.approx(4.8)
        assert multiply(-2.5, 2.0) == pytest.approx(-5.0)


class TestDivide:
    """Test cases for the divide function."""

    def test_divide_normal(self):
        """Test normal division with integer result."""
        assert divide(10, 2) == 5
        assert divide(100, 5) == 20
        assert divide(15, 3) == 5

    def test_divide_resulting_in_float(self):
        """Test division resulting in a float."""
        assert divide(10, 3) == pytest.approx(3.333333, rel=1e-5)
        assert divide(7, 2) == pytest.approx(3.5)
        assert divide(5, 4) == pytest.approx(1.25)

    def test_divide_by_zero_raises_error(self):
        """Test that dividing by zero raises a ValueError."""
        with pytest.raises(ValueError, match="Cannot divide by zero"):
            divide(10, 0)
        with pytest.raises(ValueError, match="Cannot divide by zero"):
            divide(0, 0)
        with pytest.raises(ValueError, match="Cannot divide by zero"):
            divide(-5, 0)

    def test_divide_negative_numbers(self):
        """Test dividing with negative numbers."""
        assert divide(-10, 2) == -5
        assert divide(10, -2) == -5
        assert divide(-10, -2) == 5
