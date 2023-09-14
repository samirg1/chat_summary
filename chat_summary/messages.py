import sqlite3
import sys
import os
from typing import Any, Generator, cast

from pandas import read_sql_query  # pyright: ignore[reportUnknownVariableType]
from pandas import DataFrame, Series

from chat_summary.chat import MESSAGE, ChatMember


class MessagesDB:
    def __init__(self, user: str, chat_name: str, silence_contact_error: bool) -> None:
        self._user = user
        self._chat_name = chat_name
        self._display_name = user
        self.silence_contact_error = silence_contact_error

        if user not in os.listdir("/Users"):
            print("invalid user, user not found", file=sys.stderr)
            exit(1)

        try:
            self._connection = sqlite3.connect(f"/Users/{user}/Library/Messages/chat.db")
        except (sqlite3.OperationalError, FileNotFoundError):
            print("could not connect to messages database, ensure you have the right permissions to access file", file=sys.stderr)
            exit(1)

    def _select_chat_id(self) -> int:
        chat_id = read_sql_query(
            f"""
            SELECT
                ROWID
            FROM
                chat
            WHERE
                display_name == "{self._chat_name}"
            """,
            self._connection,
        )

        if chat_id.empty:
            print("chat name not found", file=sys.stderr)
            exit(1)

        items = cast(dict[Any, list[int]], chat_id)
        return items["ROWID"][0]

    def _get_addressbook_db_path(self) -> str:
        address_source_path = f"/Users/{self._user}/Library/Application Support/AddressBook/Sources"  # base path
        for dir in os.listdir(address_source_path):
            if not dir.count("."):  # go one step in each folder
                for file in os.listdir(f"{address_source_path}/{dir}"):
                    if file.count("."):  # find the correct file
                        if file == "AddressBook-v22.abcddb":
                            return f"{address_source_path}/{dir}/{file}"
        raise FileNotFoundError

    def _get_chat_members(self, chat_id: int) -> list[ChatMember]:
        numbers: Series[str] = read_sql_query(
            f"""
            SELECT 
                id
            FROM 
                chat_handle_join c 
                JOIN 
                    handle h 
                ON 
                    c.handle_id = h.ROWID
            WHERE
                chat_id = {chat_id}
            """,
            self._connection,
        )[
            "id"
        ]  # get all numbers in a chat

        # connect to contacts
        address_path: str
        all_contacts = DataFrame()
        try:
            address_path = self._get_addressbook_db_path()
            contacts_connection = sqlite3.connect(address_path)

            all_contacts = read_sql_query(
                """
                SELECT 
                    zfirstname, zlastname, zfullnumber
                FROM
                    zabcdrecord r 
                    JOIN 
                        zabcdphonenumber p 
                    ON 
                        r.z_pk = p.zowner
                """,
                contacts_connection,
            )  # get all contacts
            contacts_connection.close()
        except (FileNotFoundError, sqlite3.OperationalError):  # contact info was not able to be found
            if not self.silence_contact_error:
                print("unable to find contacts", file=sys.stderr)
            return [ChatMember(number, number) for number in numbers] + [ChatMember(self._user, "")]

        chat_members: list[ChatMember] = []

        for number in numbers:
            for i in range(len(all_contacts)):
                first, last, contact_number = cast(tuple[str, str, str], all_contacts.iloc[i, :])  # retrieve data from all contacts
                contact_number = "".join([n for n in contact_number if n != " "])  # remove spaces
                if contact_number[0] == "0":  # replace 0 at start with +61
                    contact_number = "+61" + contact_number[1:]

                name = first or "" + " " + last or ""  # combine first and last names
                name = ("".join(n for n in name if n.isalnum() or n == " ")).strip()  # clean up

                if number == contact_number:  # add a found user and break
                    chat_members.append(ChatMember(name, number))
                    break

            else:  # if we did not find a contact, set the contact name to just the number
                chat_members.append(ChatMember(number, number))  # pragma: no cover

        chat_members.append(ChatMember(self._display_name, ""))
        return chat_members

    def _get_messages(self, chat_id: int) -> Generator[MESSAGE, None, None]:
        raw_messages = read_sql_query(
            f"""
            SELECT  
                text,
                id as phone
            FROM 
                (
                    message m 
                    JOIN 
                        chat_message_join c 
                    ON 
                        m.ROWID = c.message_id
                ) 
                LEFT OUTER JOIN
                    handle h 
                ON 
                    h.ROWID = m.handle_id
            WHERE
                chat_id = {chat_id}
            """,
            self._connection,
        )  # get all messages from the chat

        messages = ((cast(tuple[str, str], raw_messages.iloc[i, :])) for i in range(len(raw_messages)))
        return (MESSAGE(*message) for message in messages)

    def get_messages_members_from_chat(self) -> tuple[Generator[MESSAGE, None, None], list[ChatMember]]:
        chat_id = self._select_chat_id()
        members = self._get_chat_members(chat_id)
        messages = self._get_messages(chat_id)
        return messages, members
