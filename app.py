from flask import Flask, render_template, request, redirect, g
import sqlite3

from config import DATABASE, ITEM_ATTRIBUTE_LIST
from util import (
    get_current_yyyymm,
    is_there_empty_entry,
    get_total_usage_info,
    add_usage_info_to_service_detail,
)

app = Flask(__name__)

# データベースとの接続を確立する部分
# rvに接続を格納する
# row_factoryにsqlite3.Rowを設定することで、SELECTを使って返るものがタプルではなくsqlite3.Rowオブジェクト（辞書のようなもの）になる
# そのため、ret.idやret.title、ret.bodyといった形でメモの中身にアクセスすることができるようになる
# https://stackoverflow.com/questions/44009452/what-is-the-purpose-of-the-row-factory-method-of-an-sqlite3-connection-object
def connect_db(): 
    rv = sqlite3.connect(DATABASE) 
    rv.row_factory = sqlite3.Row
    return rv

# gオブジェクトはグローバル変数で、DBのデータを保存するために使われる
# gオブジェクトは、1回のリクエスト（ユーザーがWebページからFlaskアプリへ要求すること）ごとに個別なものになる
# gオブジェクトは、リクエストの（処理）期間中は複数の関数によってアクセスされるようなデータを格納するために使われる
# DBとの接続はgオブジェクトに格納されて、もしも同じリクエストの中でget_dbが2回呼び出された場合、新しい接続を作成する代わりに、再利用される
def get_db():
    # gオブジェクトはグローバル変数で、DBのデータを保存するために使われる
    # gオブジェクトは、1回のリクエスト（ユーザーがWebページからFlaskアプリへ要求すること）ごとに個別なものになる
    # gオブジェクトは、リクエストの（処理）期間中は複数の関数によってアクセスされるようなデータを格納するために使われる
    # DBとの接続はgオブジェクトに格納されて、もしも同じリクエストの中でget_dbが2回呼び出された場合、新しい接続を作成する代わりに、再利用される
    # もしgが"sqlite_db"属性でない＝まだDBに接続していないようなら、データベースと接続する
    if not hasattr(g, "sqlite_db"):  
        g.sqlite_db = connect_db()
    # これで一時的にDBとの接続を保存する。これに対してSQL文を投げる
    return g.sqlite_db  

# トップ画面を表示
@app.route("/")
def top():  
    yyyymm = get_current_yyyymm()
    # 接続を確立
    db = get_db() 
    service_detail_list = db.execute( 
        "select * from service where year_month = ?", [yyyymm]
    ).fetchall() 

    if service_detail_list != []: 
        item_detail_list = db.execute(
            "select * from item where purchase_date like ?", [yyyymm + "%"]
        ).fetchall() 
        expense_for_each_service = {
            service_detail["service_name"]: 0 for service_detail in service_detail_list
        }
        for item in item_detail_list:
            if item["service_name"] in expense_for_each_service:
                expense_for_each_service[item["service_name"]] += item["item_price"]

        service_detail_list_with_each_data = []
        for service_detail in service_detail_list:
            service_detail_dict = add_usage_info_to_service_detail(
                service_detail, expense_for_each_service[service_detail["service_name"]]
            )
            service_detail_list_with_each_data.append(service_detail_dict)

        total_current_usage = sum(expense_for_each_service.values())
        total_upper_limit = sum(
            [service_detail["upper_limit"] for service_detail in service_detail_list]
        )
        total_usage_ratio = round((total_current_usage * 100 / total_upper_limit), 1)
        text_style_total_usage_ratio = f"width:{total_usage_ratio}%"
        total_usage_ratio_with_percent = f"{total_usage_ratio}%"

        return render_template(
            "index.html",
            year=yyyymm[:4],
            month=yyyymm[5:],
            total_upper_limit=total_upper_limit,
            total_current_usage=total_current_usage,
            text_style_total_usage_ratio=text_style_total_usage_ratio,
            total_usage_ratio_with_percent=total_usage_ratio_with_percent,
            service_detail_list=service_detail_list_with_each_data,
        )
    else:
        is_service_exist = db.execute("select * from service").fetchone()
        if is_service_exist != None:
            newest_service = db.execute(
                "select * from service where service_id = (select max(service_id) from service)"
            ).fetchone()
            most_recent_day_recorded = newest_service["year_month"]
            service_detail_list = db.execute( 
                "select * from service where year_month = ?", [most_recent_day_recorded]
            )
            service_detail_list_with_each_data = []
            for service_detail in service_detail_list:
                service_detail_dict = add_usage_info_to_service_detail(
                    service_detail=service_detail, current_usage=0
                )
                service_detail_list_with_each_data.append(service_detail_dict)

                db.execute( 
                    "insert into service (year_month, service_name, upper_limit) values (?, ?, ?)",
                    [
                        yyyymm,
                        service_detail_dict["service_name"],
                        service_detail_dict["upper_limit"],
                    ],
                )
                db.commit()
            total_upper_limit = sum(
                [
                    service_detail["upper_limit"]
                    for service_detail in service_detail_list_with_each_data
                ]
            )

            return render_template(
                "index.html",
                year=yyyymm[:4],
                month=yyyymm[5:],
                total_upper_limit=total_upper_limit,
                total_current_usage=0,
                text_style_total_usage_ratio=f"width:{0}%",
                total_usage_ratio_with_percent=f"{0}%",
                service_detail_list=service_detail_list_with_each_data,
            )
        else:
            return render_template(
                "index.html",
                year=yyyymm[:4],
                month=yyyymm[5:],
                total_current_usage=0,
                total_upper_limit=0,
                text_style_total_usage_ratio="width:0%",
                total_usage_ratio_with_percent="-",
                service_detail_list=service_detail_list,
            )


# ここから固定費登録画面
@app.route("/service_detail")
def show_registered_services():
    yyyymm = get_current_yyyymm()
    db = get_db()
    service_detail_list = db.execute( 
        "select * from service where year_month = ?", [yyyymm]
    ).fetchall()
    return render_template(
        "service_detail.html", service_detail_list=service_detail_list
    )


# ここから商品画面
@app.route("/services_detail")
def show_items():
    yyyymm = get_current_yyyymm()
    db = get_db() 
    items_detail_list = db.execute( 
        "select * from item where year_month = ?", [yyyymm]
    ).fetchall()
    return render_template(
        "services_detail.html", items_detail_list=items_detail_list
    )


@app.route("/service_register", methods=["GET", "POST"])
def register_new_service(error_message=""): 
    db = get_db()
    is_any_service_exists = db.execute( 
        "select * from service"
    ).fetchone()
    if request.method == "POST":
        service_name = request.form.get("service_name") 
        upper_limit = request.form.get("upper_limit") 
        yyyymm = get_current_yyyymm()
        is_existed_service = db.execute(
            "select service_name from service where service_name = ? and year_month = ?",
            [service_name, yyyymm],
        ).fetchall()

        # 同名の固定費がある場合・入力が空欄の場合のエラーキャッチ
        if is_existed_service:
            return render_template(
                "service_register.html", error_message="同じ名前の固定費が既に存在しています"
            )
        if service_name == "" or upper_limit == "":
            return render_template(
                "service_register.html", error_message="固定費名もしくは使用上限金額が空欄です"
            )

        # ここからDBに登録する処理
        register_body = {
            "year_month": yyyymm,
            "service_name": service_name,
            "upper_limit": upper_limit,
        }
        statement = "".join(
            [
                "insert into service (",
                ", ".join("`" + key + "`" for key in register_body.keys()),
                ") values (",
                ", ".join(["?"] * len(register_body)),
                ")",
            ]
        )
        db.execute(statement, [value for value in register_body.values()])
        db.commit() 
        return redirect("/service_detail") 
    if is_any_service_exists is None:
        error_message = "固定費が登録されていません。まずは購入した商品と、使用する上限金額を登録してください。"
    return render_template("service_register.html", error_message=error_message)


@app.route("/<service_name>/service_edit", methods=["GET", "POST"])
def edit_service(service_name):
    db = get_db()
    yyyymm = get_current_yyyymm()
    post = db.execute(
        "select service_name, upper_limit from service where service_name = ? and year_month = ?",
        [service_name, yyyymm],
    ).fetchone()

    # 編集完了ボタンが押された時の処理
    if request.method == "POST":
        service_name = request.form.get("service_name") 
        upper_limit = request.form.get("upper_limit") 

        # 入力が空欄の場合のエラーキャッチ
        if upper_limit == "":
            return render_template(
                "service_edit.html", error_message="使用上限金額が空欄です", post=post
            )

        # DBに上書き登録する処理
        db.execute(
            "update service set upper_limit = ? where service_name = ? and year_month = ?",
            [upper_limit, service_name, yyyymm],
        )
        db.commit()
        return redirect("/service_detail") 

    return render_template("service_edit.html", error_message="", post=post)


@app.route("/<service_name>/service_delete", methods=["GET", "POST"])
def delete_service(service_name): 
    db = get_db()
    yyyymm = get_current_yyyymm()

    if request.method == "POST":
        service_name = request.form.get("service_name") 

        # DBからサービスを削除する
        db.execute(
            "delete from service where service_name = ? and year_month = ?",
            [service_name, yyyymm],
        )
        db.commit()
        return redirect("/service_detail") 

    post = db.execute(
        "select service_name, upper_limit from service where service_name = ? and year_month = ?",
        [service_name, yyyymm],
    ).fetchone()
    return render_template("service_delete.html", post=post)


# ここから商品画面
@app.route("/<service_name>/<yyyymm>/item_detail")
def show_registered_items(service_name, yyyymm): 
    db = get_db()  # 接続を確立
    item_detail_list = db.execute( 
        "select * from item where purchase_date like ? and service_name = ?",
        [
            yyyymm + "%",
            service_name,
        ],
    ).fetchall()
    service_data = db.execute(
        "select service_name, upper_limit from service where service_name = ? and year_month = ?",
        [service_name, yyyymm],
    ).fetchone()

    if service_data is not None:
        service_detail = add_usage_info_to_service_detail(
            service_data, sum([item["item_price"] for item in item_detail_list])
        )

        return render_template(
            "item_detail.html",
            item_detail_list=item_detail_list,
            year=yyyymm[:4],
            month=yyyymm[5:],
            service_detail=service_detail,
        )
    else: 
        service_detail = {
            "service_name": service_name,
            "current_usage": sum([item["item_price"] for item in item_detail_list]),
            "upper_limit": 0,
            "text_style_usage_ratio": "width:0.0%",
            "usage_ratio_with_percent": "-",
        }

        return render_template(
            "item_detail.html",
            item_detail_list=item_detail_list,
            year=yyyymm[:4],
            month=yyyymm[5:],
            service_detail=service_detail,
        )

# 新しい商品を登録する
@app.route("/item_register", methods=["GET", "POST"])
def register_new_item():  
    db = get_db()
    yyyymm = get_current_yyyymm()
    service_detail_list = db.execute(
        "select * from service where year_month = ?", [yyyymm]
    ).fetchall()
    if service_detail_list == []:
        return redirect("/service_register")

    if request.method == "POST": 
        purchase_date = request.form.get("purchase_date")  
        service_name = request.form.get("service_name")  
        item_name = request.form.get("item_name")  
        item_price = request.form.get("item_price") 
        item_attribute = request.form.get("item_attribute") 

        is_existed_item = db.execute( 
            "select service_name, item_name from item where service_name = ? and item_name = ?",
            [
                service_name,
                item_name,
            ],
        ).fetchall()

        # 同じ商品が同じサービスで購入されている場合・入力が空欄の場合のエラーキャッチ
        if is_existed_item:
            return render_template(
                "item_register.html",
                error_message=f"同じ名前の商品が{service_name}で既に購入されています",
                service_detail_list=service_detail_list,
                item_attribute_list=ITEM_ATTRIBUTE_LIST,
            )
        if (
            is_there_empty_entry(
                [
                    purchase_date,
                    service_name,
                    item_name,
                    item_price,
                    item_attribute,
                ]
            )
            is True
        ):
            return render_template(
                "item_register.html",
                error_message="全て入力してください",
                service_detail_list=service_detail_list,
                item_attribute_list=ITEM_ATTRIBUTE_LIST,
            )

        # ここからDBに登録する処理
        register_body = {
            "purchase_date": purchase_date,
            "service_name": service_name,
            "item_name": item_name,
            "item_price": item_price,
            "item_attribute": item_attribute,
        }
        statement = "".join(
            [
                "insert into item (",
                ", ".join("`" + key + "`" for key in register_body.keys()),
                ") values (",
                ", ".join(["?"] * len(register_body)),
                ")",
            ]
        )  
        db.execute(statement, [value for value in register_body.values()])
        db.commit() 
        return redirect(
            f"/{service_name}/{purchase_date[:7]}/item_detail"
        )  # DBに新たなサービスを入れたら、商品登録画面に戻る

    return render_template(
        "item_register.html",
        error_message="",
        service_detail_list=service_detail_list,
        item_attribute_list=ITEM_ATTRIBUTE_LIST,
    )


@app.route("/<service_name>/item_edit/<item_id>", methods=["GET", "POST"])
def edit_item(service_name, item_id):
    yyyymm = get_current_yyyymm()
    db = get_db() 
    service_detail_list = db.execute( 
        "select * from service where year_month = ?", [yyyymm]
    ).fetchall()
    objective_item = db.execute(
        "select * from item where item_id = ?", [item_id]
    ).fetchone()
    # 登録ボタンが押された場合の処理
    if request.method == "POST":
        # request.form.getで得られるのは全部str型
        purchase_date = request.form.get("purchase_date") 
        service_name = request.form.get("service_name") 
        item_name = request.form.get("item_name") 
        item_price = request.form.get("item_price") 
        item_attribute = request.form.get("item_attribute")  

        is_existed_item = db.execute(  
            "select service_name, item_name from item where service_name = ? and item_name = ? and item_id != ?",
            [service_name, item_name, item_id],
        ).fetchall() 

        # 同名の商品が変更先のサービスで購入されている場合のエラーキャッチ
        if is_existed_item:
            return render_template(
                "item_edit.html",
                error_message=f"同じ名前の商品が{service_name}で既に購入されています",
                objective_item=objective_item,
                service_detail_list=service_detail_list,
                item_attribute_list=ITEM_ATTRIBUTE_LIST,
            )

        # 入力が空欄の場合のエラーキャッチ
        if (
            is_there_empty_entry(
                [
                    purchase_date,
                    service_name,
                    item_name,
                    item_price,
                    item_attribute,
                ]
            )
            is True
        ):
            return render_template(
                "item_edit.html",
                error_message="全て入力してください",
                objective_item=objective_item,
                service_detail_list=service_detail_list,
                item_attribute_list=ITEM_ATTRIBUTE_LIST,
            )

        # DBに上書き登録する処理
        db.execute(
            "update item set purchase_date = ?, service_name = ?, item_name = ?, item_price = ?, item_attribute = ? where item_id = ?",
            [
                purchase_date,
                service_name,
                item_name,
                item_price,
                item_attribute,
                item_id,
            ],
        )
        db.commit()
        return redirect(
            f"/{service_name}/{purchase_date[:7]}/item_detail"
        ) 

    return render_template(
        "item_edit.html",
        error_message="",
        objective_item=objective_item,
        service_detail_list=service_detail_list,
        item_attribute_list=ITEM_ATTRIBUTE_LIST,
    )


@app.route("/<service_name>/item_delete/<item_id>", methods=["GET", "POST"])
def delete_item(service_name, item_id): 
    db = get_db()

    if request.method == "POST":
        # DBから商品を削除する
        purchase_date = db.execute(
            "select purchase_date from item where item_id = ?", [item_id]
        ).fetchone()["purchase_date"]
        db.execute(
            "delete from item where item_id = ?",
            [item_id],
        )
        db.commit() 
        return redirect(
            f"/{service_name}/{purchase_date[:7]}/item_detail"
        )  # DBから商品を削除したら、TOP画面に戻る

    objective_item = db.execute(
        "select * from item where item_id = ?",
        [
            item_id,
        ],
    ).fetchone()
    yyyymm = get_current_yyyymm()
    service_detail_list = db.execute(
        "select * from service where year_month = ?", [yyyymm]
    ).fetchall()
    return render_template(
        "item_delete.html",
        objective_item=objective_item,
        service_detail_list=service_detail_list,
        item_attribute_list=ITEM_ATTRIBUTE_LIST,
    )


@app.route("/history", methods=["GET", "POST"])
def show_graph():
    db = get_db()
    service_detail_list = db.execute(
        "select * from service",
    ).fetchall()
    recorded_year_month_list = list(
        set([service_detail["year_month"] for service_detail in service_detail_list])
    )
    recorded_year_month_list.sort()

    total_upper_limit_and_usage_for_each_month = {}
    for year_month in recorded_year_month_list:
        total_upper_limit_and_usage_for_each_month[year_month] = {
            "total_upper_limit": 0,
            "total_usage": 0,
        }

    for service_detail in service_detail_list:
        total_upper_limit_and_usage_for_each_month[service_detail["year_month"]][
            "total_upper_limit"
        ] += service_detail["upper_limit"]

    item_detail_list = db.execute("select * from item").fetchall()
    for item_detail in item_detail_list:
        # サービスの使用上限金額が決まっている月に購入された商品のみ購入する
        if (
            item_detail["purchase_date"][:7]
            in total_upper_limit_and_usage_for_each_month
        ):
            total_upper_limit_and_usage_for_each_month[
                item_detail["purchase_date"][:7]
            ]["total_usage"] += item_detail["item_price"]

    total_upper_limit = [
        total_upper_limit_and_usage["total_upper_limit"]
        for total_upper_limit_and_usage in total_upper_limit_and_usage_for_each_month.values()
    ]
    total_usage = [
        total_upper_limit_and_usage["total_usage"]
        for total_upper_limit_and_usage in total_upper_limit_and_usage_for_each_month.values()
    ]

    # グラフの見栄えを良くするために、最初に記録された月より一ヶ月前にデータを追加する
    if recorded_year_month_list: 
        first_recorded_year_month = recorded_year_month_list[0]
        if first_recorded_year_month[5:] == "01":
            previous_year = str(int(first_recorded_year_month[:4]) - 1)
            previous_month = "12"
            recorded_year_month_list = [
                previous_year + "-" + previous_month
            ] + recorded_year_month_list
            total_upper_limit = [0] + total_upper_limit
            total_usage = [0] + total_usage
        else:
            previous_month = str(int(first_recorded_year_month[5:]) - 1).zfill(2)
            recorded_year_month_list = [
                first_recorded_year_month[:4] + "-" + previous_month
            ] + recorded_year_month_list
            total_upper_limit = [0] + total_upper_limit
            total_usage = [0] + total_usage

    return render_template(
        "line_graph.html",
        recorded_year_month_list=recorded_year_month_list,
        total_upper_limit=total_upper_limit,
        total_usage=total_usage,
        sum_of_total_upper_limit=sum(total_upper_limit),
        sum_of_total_usage=sum(total_usage),
    )




con = sqlite3.connect(DATABASE)
cur = con.cursor()
cur.execute(
    "create table if not exists service(service_id integer primary key autoincrement, year_month text not null, service_name text not null, upper_limit integer not null)"
)
cur.execute(
    "create table if not exists item(item_id integer primary key autoincrement, purchase_date text not null, service_name text not null, item_name text not null, item_price integer not null, item_attribute text not null)"
)
cur.execute(
    "create table if not exists extra_item(extra_item_id integer primary key autoincrement, purchase_date text not null, service_name text not null, extra_item_name text not null, extra_item_price integer not null, extra_item_attribute text not null)"
)
con.close()
app.run(debug=True)  # debug=Trueでリロードすればコードの変更が反映される
