from PyQt6.QtWidgets import QInputDialog, QLineEdit, QMessageBox


def ask_password(self):
    password, ok = QInputDialog.getText(self, "Password", "Enter your sudo password:",
                                        QLineEdit.EchoMode.Password)
    if ok and password:
        return password
    return None


def ask_confirmation(title, message):
    msg = QMessageBox()
    msg.setWindowTitle(title)
    msg.setText(message)
    msg.setIcon(QMessageBox.Icon.Question)
    msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

    result = msg.exec()
    return result == QMessageBox.StandardButton.Yes

def ask_native_or_flatpak(option1, option2, title, message):
    msg = QMessageBox()
    msg.setWindowTitle(title)
    msg.setText(message)
    msg.setIcon(QMessageBox.Icon.Question)

    button1 = msg.addButton(option1, QMessageBox.ButtonRole.AcceptRole)
    button2 = msg.addButton(option2, QMessageBox.ButtonRole.AcceptRole)
    msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    msg.exec()

    if msg.clickedButton() == button1:
        return option1
    elif msg.clickedButton() == button2:
        return option2
    else:
        return None  #for cancel or any other case

def show_info(title, message):
    msg = QMessageBox()
    msg.setWindowTitle(title)
    msg.setText(message)
    msg.setIcon(QMessageBox.Icon.Information)
    msg.setStandardButtons(QMessageBox.StandardButton.Ok)
    msg.exec()
