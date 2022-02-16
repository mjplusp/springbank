class BotException(Exception):
  def __init__(self):
    super().__init__('Bot Exception')

class NoBotPropertiesException(BotException):
  def __init__(self):
    super().__init__('No Bot Properties')

class NoBotPropertiesAdvancedException(BotException):
  def __init__(self):
    super().__init__('No Advanced Bot Properties')