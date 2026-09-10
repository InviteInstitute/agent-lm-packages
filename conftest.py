"""Repository-wide pytest options; goal fixtures live with the goal tests."""
def pytest_addoption(parser):
    parser.addoption("--require-goal-data", action="store_true",
                     help="Fail if any private goal validation input is missing")
