import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel, QLineEdit, QPushButton, QMessageBox, QVBoxLayout, QWidget, QStackedWidget, QTextEdit, QHBoxLayout, QFileDialog, QListWidget, QInputDialog
from PyQt5.QtCore import Qt, pyqtSignal
import socket
import json
import os
import threading
import logging
import time
import queue
from datetime import datetime
import struct
import pickle

sys.path.append(".")
from utils import MessageBuilder as mb

global_lock = threading.Lock()


class CurrentUser:
    username = None

    @staticmethod
    def set_username(username):
        CurrentUser.username = username

    @staticmethod
    def del_username():
        CurrentUser.username = None

    @staticmethod
    def get_username():
        return CurrentUser.username


class ChatConnection:

    def __init__(self, host, port, heartbeat_interval=10, timeout=30):
        self.host = host
        self.port = port
        self.server_socket = None
        self.heartbeat_interval = heartbeat_interval
        self.timeout = timeout
        self.lock = threading.Lock()
        self.response_cache = None
        self.parent = None

        self.friend_status_cache = None

    def start_connect(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.connect((self.host, self.port))
        listen_thread = threading.Thread(target=self.handle_server)
        listen_thread.start()
        threading.Thread(target=self.send_heartbeat).start()

    def disconnect(self):
        with self.lock:
            if self.server_socket:
                self.server_socket.close()
                self.server_socket = None

    def handle_server(self):
        last_heartbeat_time = datetime.now()
        self.server_socket.settimeout(15)
        while True:
            try:
                message_json = self.server_socket.recv(1024).decode('utf-8')
                logging.info(f"Received message: {message_json}")
                message = json.loads(message_json)
                # message_length = int.from_bytes(self.server_socket.recv(4), byteorder='big')
                # message_bytes = self.server_socket.recv(message_length)
                # message = pickle.loads(message_bytes)
                if message['type'] != 'file_data':
                    logging.info(f"Received message: {message}")

                last_heartbeat_time = datetime.now()
                message_type = message.get('type')
                if message_type == 'heartbeat':
                    logging.debug("Received heartbeat from server")
                elif message_type == 'response':
                    self.response_cache = message
                else:
                    self.handle_message(message)
            except socket.timeout:
                logging.debug("Socket timeout")
                if (datetime.now() - last_heartbeat_time).total_seconds() > self.timeout:
                    logging.info("Server timeout")
                self.disconnect()
            except json.JSONDecodeError:
                logging.error("Error decoding JSON message")
            except KeyError as e:
                logging.error(f"Missing key in message: {e}")

    def handle_message(self, message):  # TODO 收到消息后在此进行处理
        if message['type'] == 'personal_message':
            sender = message['sender']
            content = message['content']
            timestamp = message['timestamp']
            timestamp_datetime = datetime.fromtimestamp(timestamp)
            formatted_timestamp = timestamp_datetime.strftime("%m-%d %H:%M")
            string = f"[{formatted_timestamp}]{sender}->You:\n{content}"
            self.parent.chat_page.display_message(string, sender)

        if message['type'] == 'file_tranfer_header':
            file_path = os.path.dirname(__file__) + '\\' + message['file_name']
            with open(file_path, 'wb') as fp:
                pass

            self.parent.chat_page.display_message(
                message['file_name'] + ' ' + str(message['file_size'])
            )  # test 输出传输文件信息

        if message['type'] == 'file_data':
            file_path = os.path.dirname(__file__) + '\\' + message['file_name']
            with open(file_path, 'ab') as fp:
                data = message['file_content']
                fp.write(data)
            pass

    def send_message(self, message):
        if not self.server_socket:
            self.start_connect()
        with self.lock:
            try:
                message_json = json.dumps(message)
                logging.info(f"Sending message: {message_json}")
                self.server_socket.send(message_json.encode('utf-8'))
                # message_bytes = pickle.dumps(message)
                # self.server_socket.send(len(message_bytes).to_bytes(4, byteorder='big'))
                # self.server_socket.send(message_bytes)
            except Exception as e:
                logging.error(str(e))

    def send_heartbeat(self):
        while self.server_socket is not None:
            try:
                username = CurrentUser.get_username()
                if username is not None:
                    message = mb.build_heartbeat(username)
                    self.send_message(message)
            except Exception as e:
                logging.error(f"Error sending heartbeat:{str(e)}")
            time.sleep(self.heartbeat_interval)

    def get_response(self, request_timestamp, timelimit=1):  # FIXME
        start_time = time.time()
        while (self.response_cache is None or self.response_cache['timestamp'] < request_timestamp):
            if (time.time() - start_time > timelimit): break

        # if self.response_cache is None:
        #     return False

        if self.response_cache['timestamp'] == request_timestamp:
            return self.response_cache
        else:
            return False  # MARK 更改了函数的返回值，从tuple改成bool


class ChatClient(QMainWindow):
    response_signal = pyqtSignal(dict)  # MARK

    def __init__(self, host, port):
        super().__init__()

        self.connection = ChatConnection(host, port)
        self.host = host
        self.port = port
        self.lock = threading.Lock()
        self.username = None
        self.connection.parent = self
        self.response_signal.connect(self.show_response)
        # region 窗口组件
        self.setWindowTitle("Chat Client")
        self.setGeometry(100, 100, 300, 150)
        self.setMinimumSize(800, 900)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.main_page = MainPage(self)
        self.register_page = RegisterPage(self)
        self.login_page = LoginPage(self)
        self.delete_page = DeletePage(self)
        self.chat_page = ChatPage(self)

        self.stack.addWidget(self.main_page)
        self.stack.addWidget(self.register_page)
        self.stack.addWidget(self.login_page)
        self.stack.addWidget(self.delete_page)
        self.stack.addWidget(self.chat_page)
        # endregion

    # region 切换页面
    def show_login_page(self):
        self.stack.setCurrentWidget(self.login_page)
        self.clear_text(self.login_page)

    def show_register_page(self):
        self.stack.setCurrentWidget(self.register_page)
        self.clear_text(self.register_page)

    def show_delete_page(self):
        self.stack.setCurrentWidget(self.delete_page)
        self.clear_text(self.delete_page)

    def show_main_page(self):
        self.stack.setCurrentWidget(self.main_page)

    def show_chat_page(self):
        self.stack.setCurrentWidget(self.chat_page)
        self.clear_text(self.chat_page)  # 在打开聊天页面时清理之前的聊天痕迹

    # end region
    @staticmethod
    def clear_text(widget):
        if isinstance(widget, (QLineEdit, QTextEdit)):
            widget.clear()
        elif isinstance(widget, QWidget):
            for child in widget.findChildren((QLineEdit, QTextEdit)):
                child.clear()

    def show_response(self, response):
        if not response: return
        if response['success']:
            message = response['message']
            QMessageBox.information(self, "Success", message)
        else:
            error_message = response['message']
            QMessageBox.critical(self, "Error", error_message)
        return response['success']

    def get_response(self, request_timestamp):
        return self.connection.get_response(request_timestamp)


class MainPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.login_button = QPushButton("Login")
        self.register_button = QPushButton("Register")
        self.delete_button = QPushButton("Delete Account")

        layout = QVBoxLayout()
        layout.addWidget(self.login_button)
        layout.addWidget(self.register_button)
        layout.addWidget(self.delete_button)

        self.login_button.clicked.connect(parent.show_login_page)
        self.register_button.clicked.connect(parent.show_register_page)
        self.delete_button.clicked.connect(parent.show_delete_page)

        self.setLayout(layout)


class RegisterPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent

        self.username_label = QLabel("Username:")
        self.username_entry = QLineEdit()
        self.password_label = QLabel("Password:")
        self.password_entry = QLineEdit()
        self.password_entry.setEchoMode(QLineEdit.Password)
        self.register_button = QPushButton("Register")
        self.back_button = QPushButton("Back")

        self.register_button.clicked.connect(self.register_user)
        self.back_button.clicked.connect(parent.show_main_page)

        layout = QVBoxLayout()
        layout.addWidget(self.username_label)
        layout.addWidget(self.username_entry)
        layout.addWidget(self.password_label)
        layout.addWidget(self.password_entry)
        layout.addWidget(self.register_button)
        layout.addWidget(self.back_button)
        self.setLayout(layout)

    def register_user(self):
        username = self.username_entry.text()
        password = self.password_entry.text()
        if not username.strip() or not password.strip():
            QMessageBox.critical(self, "Error", "Username and password cannot be blank.")
            return
        message = mb.build_register_request(username, password)
        timestamp = message['timestamp']
        self.parent.connection.send_message(message)
        response = self.parent.get_response(timestamp)
        if self.parent.show_response(response):
            self.parent.show_main_page()


class LoginPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent

        self.username_label = QLabel("Username:")
        self.username_entry = QLineEdit()
        self.password_label = QLabel("Password:")
        self.password_entry = QLineEdit()
        self.password_entry.setEchoMode(QLineEdit.Password)
        self.login_button = QPushButton("Login")
        self.back_button = QPushButton("Back")

        self.login_button.clicked.connect(self.login_user)
        self.back_button.clicked.connect(parent.show_main_page)

        layout = QVBoxLayout()
        layout.addWidget(self.username_label)
        layout.addWidget(self.username_entry)
        layout.addWidget(self.password_label)
        layout.addWidget(self.password_entry)
        layout.addWidget(self.login_button)
        layout.addWidget(self.back_button)
        self.setLayout(layout)

    def login_user(self):
        username = self.username_entry.text()
        password = self.password_entry.text()
        if not username.strip() or not password.strip():
            QMessageBox.critical(self, "Error", "Username and password cannot be blank.")
            return
        message = mb.build_login_request(username, password)
        timestamp = message['timestamp']
        self.parent.connection.send_message(message)
        response = self.parent.get_response(timestamp)
        if self.parent.show_response(response):
            CurrentUser.set_username(username)
            self.parent.show_chat_page()


class DeletePage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent

        self.username_label = QLabel("Username:")
        self.username_entry = QLineEdit()
        self.password_label = QLabel("Password:")
        self.password_entry = QLineEdit()
        self.password_entry.setEchoMode(QLineEdit.Password)
        self.delete_button = QPushButton("Delete Account")
        self.back_button = QPushButton("Back")

        self.delete_button.clicked.connect(self.delete_account)
        self.back_button.clicked.connect(parent.show_main_page)

        layout = QVBoxLayout()
        layout.addWidget(self.username_label)
        layout.addWidget(self.username_entry)
        layout.addWidget(self.password_label)
        layout.addWidget(self.password_entry)
        layout.addWidget(self.delete_button)
        layout.addWidget(self.back_button)
        self.setLayout(layout)

    def delete_account(self):
        username = self.username_entry.text()
        password = self.password_entry.text()
        if not username.strip() or not password.strip():
            QMessageBox.critical(self, "Error", "Username and password cannot be blank.")
            return
        confirmation = QMessageBox.question(
            self, "Confirmation", "Are you sure you want to delete your account?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirmation == QMessageBox.Yes:
            message = mb.build_delete_request(username, password)
            timestamp = message['timestamp']
            self.parent.connection.send_message(message)
            response = self.parent.get_response(timestamp)
            if self.parent.show_response(response):
                self.parent.show_main_page()


class ChatPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent

        self.current_friend = None
        self.chat_pages = QStackedWidget()
        self.friend_list = QListWidget()
        self.init_UI()

        # threading.Thread(target=self.__update_friend_status, daemon=True).start()

    def init_UI(self):
        layout = QHBoxLayout(self)
        self.setGeometry(100, 100, 800, 600)

        friend_list = ['None']
        self.friend_list.addItems(friend_list)  # TEST
        self.friend_list.setFixedWidth(150)
        self.friend_list.itemClicked.connect(self.__change_selected_friend)
        layout.addWidget(self.friend_list)

        self.chat_pages.setMinimumWidth(400)
        for friend in friend_list:
            chat = self.__chatpage_factory(friend)
            if chat is not None:
                self.chat_pages.addWidget(chat)
        layout.addWidget(self.chat_pages)

        self.setLayout(layout)
        self.setWindowTitle("Chat Page")
        # self.setMinimumSize(700, 650)
        # self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        pass

    def __change_selected_friend(self, item):
        '''
        更改当前好友选择
        '''
        friend_name = item.text()
        self.current_friend = friend_name
        self.chat_pages.setCurrentWidget(self.chat_pages.findChild(QWidget, friend_name))

    def __chatpage_factory(self, friend_name: str):
        '''
        根据名字生成聊天界面
        '''
        chat = QWidget()  # 当前好友聊天界面
        chat.setObjectName(friend_name)

        min_width = 400
        min_height = 180

        layout = QVBoxLayout()

        # 当前好友状态显示
        chat.setProperty('status', 'offline')
        status_label = QLabel(f'{friend_name}状态:' + chat.property('status'))
        status_label.setObjectName('StatusLabel')
        status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(status_label)

        # 聊天消息显示
        message_displayer = QTextEdit()
        message_displayer.setReadOnly(True)
        message_displayer.setObjectName('MessageDisplayer')
        message_displayer.setMinimumWidth(min_width)
        message_displayer.setMinimumHeight(min_height)
        layout.addWidget(message_displayer)

        # 发送消息编辑框
        message_editor = QTextEdit()
        message_editor.setObjectName('MessageEditor')
        message_editor.setMinimumWidth(min_width)
        message_editor.setMinimumHeight(min_height)
        layout.addWidget(message_editor)

        button_layout = QHBoxLayout()
        # 发送消息按钮
        send_message_button = QPushButton("Send Message")
        send_message_button.setObjectName('SendMessageButton')
        send_message_button.clicked.connect(self.send_message)
        # send_message_button.setFixedSize(200, 30)
        button_layout.addWidget(send_message_button)
        # 发送文件按钮
        send_file_button = QPushButton("Send File")
        send_file_button.setObjectName('SendFileButton')
        send_file_button.clicked.connect(self.send_file)
        # send_file_button.setFixedSize(200, 30)
        button_layout.addWidget(send_file_button)

        layout.addLayout(button_layout)

        del button_layout
        button_layout = QHBoxLayout()
        # 添加好友按钮
        add_friend_button = QPushButton("Add Friend")
        add_friend_button.setObjectName('AddFriendButton')
        add_friend_button.clicked.connect(self.add_friend)
        button_layout.addWidget(add_friend_button)
        # 删除好友按钮
        delete_friend_button = QPushButton("Delete Friend")
        delete_friend_button.setObjectName('DeleteFriendButton')
        delete_friend_button.clicked.connect(self.remove_friend)
        button_layout.addWidget(delete_friend_button)

        layout.addLayout(button_layout)
        # 返回主界面按钮
        back_button = QPushButton("Back")
        back_button.setObjectName('BackButton')
        back_button.clicked.connect(self.parent.show_main_page)
        layout.addWidget(back_button)

        chat.setLayout(layout)

        return chat

    def __update_friend_status(self):
        # XXX 由于使用多线程时无法运行，所以在调用display_message时更新好友列表

        # time.sleep(2)
        # while True:
        update_friend_list_request = mb.build_get_friends_request(CurrentUser.get_username())
        self.parent.connection.send_message(update_friend_list_request)
        response = self.parent.get_response(update_friend_list_request['timestamp'])
        # if response is False:
        #     # continue
        #     return

        if isinstance(response, bool):
            return

        if response['success']:

            friend_list = response['data']
            if friend_list is None:
                # continue
                return

            for index in range(self.friend_list.count()):  # 遍历好友列表，删除好友
                item = self.friend_list.item(index)
                username = item.text()

                status = friend_list.get(username)
                if status == None:
                    # 好友已经被删除
                    if username != 'None':
                        self.handle_delete_friend(username)

                else:
                    chat = self.chat_pages.findChild(QWidget, username)
                    chat.setProperty('status', status)
                    status_label = chat.findChild(QLabel, 'StatusLabel')
                    status_label.setText(f'{username}状态:{status}')

            for key, value in friend_list.items():
                if self.friend_list.findItems(key, Qt.MatchExactly):  # 好友列表存在该好友
                    continue

                chat = self.__chatpage_factory(key)
                chat.setProperty('status', value)
                label = chat.findChild(QLabel, 'StatusLabel')
                label.setText(f'{key}状态:{value}')

                self.friend_list.addItem(key)
                self.chat_pages.addWidget(chat)

            # time.sleep(10)

    def add_friend(self, friend_name):  # TODO 主动添加好友
        user_name, status = QInputDialog.getText(self, "Add Friend", "Enter the username of the friend:")
        if status == False:
            return

        add_friend_request = mb.build_add_friend_request(CurrentUser.get_username(), user_name)
        self.parent.connection.send_message(add_friend_request)

        timestamp = add_friend_request['timestamp']
        response = self.parent.get_response(timestamp)  # 单向添加好友
        if not response['success']:
            return

        chat = self.__chatpage_factory(user_name)
        if chat is None:
            QMessageBox.critical(self, "Error", "Failed to add friend.")
        self.friend_list.addItem(user_name)
        self.chat_pages.addWidget(chat)

        # 单向添加，
        pass  # 可以在聊天界面中删除好友

    def remove_friend(self, friend_name):  # TODO 主动删除好友
        pass  # 删除当前好友

    def handle_add_friend(self, user_name):  # TODO 处理对方添加你为好友的情况
        for i in range(self.friend_list.count()):  # 遍历好友列表
            if self.friend_list.item(i).text() == user_name:
                return

        chat = self.__chatpage_factory(user_name)
        self.friend_list.addItem(user_name)
        self.chat_pages.addWidget(chat)

    def handle_delete_friend(self, user_name):  # TODO 处理对方删除你的情况

        index = self.chat_pages.findChild(QWidget, user_name)
        self.chat_pages.removeWidget(index)
        index.deleteLater()

        index = self.friend_list.findItems(user_name, Qt.MatchExactly)
        for item in index:
            self.friend_list.takeItem(self.friend_list.row(item))

        if user_name == self.current_friend:
            page = self.friend_list.findItems("None", Qt.MatchExactly)
            self.__change_selected_friend(page[0])

    def send_message(self):
        if self.current_friend is None:
            QMessageBox.critical(self, "Error", "Please select a friend to send message.")
            return

        editor = self.chat_pages.currentWidget().findChild(QTextEdit, 'MessageEditor')
        displayer = self.chat_pages.currentWidget().findChild(QTextEdit, 'MessageDisplayer')
        friend_name = self.current_friend

        message = editor.toPlainText()
        if message == '':
            return

        if self.current_friend == 'None':
            self.display_message(message, friend_name)
            return

        message_packet = mb.build_send_personal_message_request(
            CurrentUser.get_username(), friend_name, message
        )
        self.parent.connection.send_message(message_packet)
        self.display_message(message, friend_name)

        # editor.clear() # 清空编辑框 # TEST

    def display_message(self, message, target=None):
        chat = self.chat_pages.findChild(QWidget, target)
        if chat is None:  # MARK 如果不是好友，不做处理
            return

        displayer = chat.findChild(QTextEdit, 'MessageDisplayer')
        displayer.append(message + '\n')
        name = CurrentUser.get_username()
        if name != None:
            displayer.append(name + '\n')
        displayer.moveCursor(displayer.textCursor().End)

        self.__update_friend_status()

        # 之后可以增加消息弹窗提示

    def send_file(self):  # TODO 使用QThread发送、接收文件，完毕后弹窗
        pass

    def receive_file(self):  # TODO 接收文件
        pass


def config_logging(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'):
    logger = logging.getLogger()
    logger.setLevel(level)
    if not logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter(format)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        args = sys.argv
        if len(args) >= 1:
            logfilename = args[1] + '-debug.log'
        else:
            logfilename = 'c-debug.log'
        file_handler = logging.FileHandler(logfilename)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)


def debug_func(client):
    connection = client.connection
    args = sys.argv
    if len(args) >= 1:
        username = 'user' + args[1]
    else:
        username = 'user'
    password = '123'
    register_msg = mb.build_register_request(username, password)
    login_msg = mb.build_login_request(username, password)
    connection.send_message(register_msg)
    time.sleep(1)
    connection.send_message(login_msg)
    CurrentUser.set_username(username)
    client.show_chat_page()
    client.setWindowTitle(username)

    # num = 0 # TEST
    # if args[1] == '1':
    #     num = 2
    # else:
    #     num = 1
    # client.chat_page.handle_add_friend('user' + str(num))


if __name__ == '__main__':
    config_logging()
    if os.environ.get('LOCAL') == 'True':
        ip_address = '127.0.0.1'
    else:
        domain_name = "wdc.zone"
        ip_address = socket.gethostbyname(domain_name)
    app = QApplication(sys.argv)
    client = ChatClient(ip_address, 9999)
    client.show()
    if os.environ.get('DEBUG') == 'True':
        debug_func(client)
    sys.exit(app.exec_())
