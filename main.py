import streamlit as st
from initialize import init_session_state
from components import sidebar_component, content_card
from utils import (
    save_data, load_data, check_cache, fetch_url_details, 
    classify_and_title, permanent_delete_old_items,
    batch_delete_items, batch_update_categories, get_user_id,
    load_user_config, generate_proposal_from_data,
    get_user_profile_keywords, search_web_with_serper, generate_response_from_web,
    save_proposal_to_list, update_summary_in_data
)
from constants import APP_NAME, STATUS_PENDING, CATEGORY_TRASH, CATEGORY_PROPOSAL
from datetime import datetime
import json
import os

# 1. アプリの初期設定
st.set_page_config(page_title=APP_NAME, layout="wide")
init_session_state()

# ユーザー固有の設定とデータのロード
config = load_user_config()
all_categories = config["all_categories"]
room_data = load_data()

# 起動時にごみ箱の古いアイテムを掃除
permanent_delete_old_items()

# セッション状態の追加初期化
if "view_full_content" not in st.session_state:
    st.session_state.view_full_content = None
if "show_web_search_button" not in st.session_state:
    st.session_state.show_web_search_button = False
if "pending_query" not in st.session_state:
    st.session_state.pending_query = ""
if "last_search_links" not in st.session_state:
    st.session_state.last_search_links = []
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# --- 🛰️ A. 詳細表示モード（タイトルクリック時） ---
if st.session_state.view_full_content:
    target_url = st.session_state.view_full_content
    item = next((i for i in room_data if i['url'] == target_url), None)
    
    if item:
        if st.button("⬅️ リストに戻る"):
            st.session_state.view_full_content = None
            st.rerun()
        
        st.title(item['title'])
        st.caption(f"登録日: {item.get('created_at', '不明')}  |  カテゴリ: {', '.join(item.get('category', []))}")
        
        if CATEGORY_PROPOSAL in item.get('category', []):
            with st.container(border=True):
                st.markdown(item.get('full_content', "内容がありません。"))
        else:
            st.info(f"この記事の詳細は元のサイトでご確認ください。")
            st.markdown(f"🔗 [外部サイトを開く]({item['url']})")
            if item.get('summary') and item['summary'] != STATUS_PENDING:
                st.subheader("📝 要約・メモ")
                st.write(item['summary'].replace("AI要約:", ""))
        
        st.stop()

# --- 🚀 B. メイン表示ロジック ---

sidebar_component()
# サイドバーのボタンに合わせてデフォルトを「トップページ」に固定
selected_category = st.session_state.get("selected_category", "トップページ")

# ユーザーID等の表示（サイドバー下部）
with st.sidebar:
    st.divider()
    room_id = get_user_id()
    st.markdown(f"### 🔑 共有ID: `{room_id}`")
    st.code(f"?room={room_id}", language=None)

# CSS調整
st.markdown("""
    <style>
    div[data-testid="stVerticalBlock"] { gap: 1.2rem !important; }
    .usage-guide-text { color: #31333F; line-height: 1.6; margin-bottom: 10px; }
    .hint-text {
        background-color: #fff9e6 !important; 
        border-left: 5px solid #f1c40f !important; 
        padding: 15px 20px; border-radius: 8px; font-size: 0.88rem;
    }
    .search-suggestion {
        background-color: #e1f5fe; padding: 15px; border-radius: 10px;
        border: 1px solid #03a9f4; margin: 10px 0;
    }
    </style>
    """, unsafe_allow_html=True)

# ---------------------------------------------------------
# 条件分岐: トップページ OR カテゴリーページ
# ---------------------------------------------------------

if selected_category == "トップページ" or selected_category == "すべて":
    # --- 【トップページ専用表示】 ---
    st.title("✨ URLの追加とアドバイザー")
    st.markdown(f"""
    <div class="usage-guide-text">
        <strong>URLをペーストするだけで、AIが内容を要約しカテゴリへ自動分類します。</strong><br>
        AIアドバイザーでは、保存されたURLを元に最適な提案を行います。
    </div>
    <div class="hint-text">
        💡 <strong>AI相談のコツ：</strong><br>
        「鶏モモ肉を使ったレシピを教えて」「短時間で腹筋を鍛える方法を教えて」など、具体的に聞くと精度が向上します。
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # 1. URL入力セクション
    st.subheader("📥 新しいURLを追加")

    # 【1】まず入力フォームを表示
    with st.form("url_input_form", clear_on_submit=True):
        col_input, col_btn = st.columns([0.9, 0.1])
        with col_input:
            url = st.text_input("整理したいURLをペースト", placeholder="https://example.com/...", label_visibility="collapsed")
        with col_btn:
            submit_button = st.form_submit_button("🔍")

    # 【2】フォームのすぐ下にメッセージ表示エリアを移動
    if "save_success_msg" in st.session_state and st.session_state.save_success_msg:
        st.success(st.session_state.save_success_msg)
        # 次の操作で消えるように None を代入
        st.session_state.save_success_msg = None

    # 【3】処理ロジック
    if submit_button and url:
        cached_item = check_cache(url, room_data)
        if cached_item:
            st.info(f"既に登録されています。")
        else:
            with st.spinner("AIが解析中..."):
                raw_title, text = fetch_url_details(url)
                ai_title, ai_cats = classify_and_title(url, text, all_categories) if text else (raw_title or "タイトル不明", ["未分類"])
                
                save_data({
                    "url": url, "title": ai_title, "category": ai_cats, 
                    "summary": STATUS_PENDING, "created_at": datetime.now().strftime("%Y-%m-%d")
                })
                
                # メッセージを保存してリロード
                cats_display = "・".join(ai_cats)
                st.session_state.save_success_msg = f"✅ 「{ai_title}」を **{cats_display}** に分類して保存しました！"
                st.rerun()

    # 2. AIアドバイザー
    st.subheader("💬 AIアドバイザーに相談")
    with st.form("chat_form", clear_on_submit=True):
        col_chat, col_chat_btn = st.columns([0.9, 0.1])
        with col_chat:
            chat_prompt = st.text_input("AIに質問する", placeholder="質問を入力...", label_visibility="collapsed")
        with col_chat_btn:
            chat_submit = st.form_submit_button("🪄")

    if chat_submit and chat_prompt:
        st.session_state.chat_history = []
        st.session_state.show_web_search_button = False
        st.session_state.last_search_links = []
        st.session_state.pending_query = chat_prompt
        with st.spinner("検討中..."):
            valid_data = [item for item in room_data if CATEGORY_TRASH not in (item.get('category') if isinstance(item.get('category'), list) else [item.get('category')])]
            response = generate_proposal_from_data(chat_prompt, valid_data)
            if "【NOT_FOUND】" in response:
                st.session_state.show_web_search_button = True
            else:
                st.session_state.chat_history.append({"role": "user", "content": chat_prompt})
                st.session_state.chat_history.append({"role": "assistant", "content": response})
        st.rerun()

    # AIアドバイザー結果表示
    if st.session_state.chat_history and not st.session_state.show_web_search_button:
        latest_history = st.session_state.chat_history[-2:]
        for message in latest_history:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
        if latest_history[-1]["role"] == "assistant":
            col_save, col_web_exec = st.columns([0.25, 0.75])
            with col_save:
                if st.button("💾 提案結果を保存", use_container_width=True):
                    save_proposal_to_list(latest_history[0]["content"], latest_history[1]["content"])
                    st.toast("保存しました！")
            with col_web_exec:
                if st.button("🌐 WEB検索する", use_container_width=True):
                    with st.spinner("WEB情報を収集中..."):
                        profile = get_user_profile_keywords(room_data)
                        search_results = search_web_with_serper(st.session_state.pending_query, profile)
                        web_response, source_links = generate_response_from_web(st.session_state.pending_query, search_results, profile)
                        st.session_state.chat_history = [
                            {"role": "user", "content": st.session_state.pending_query + " (WEB検索)"},
                            {"role": "assistant", "content": web_response}
                        ]
                        st.session_state.last_search_links = source_links
                        st.rerun()

    if st.session_state.show_web_search_button:
        st.markdown(f'<div class="search-suggestion">🔍 <strong>WEB検索の提案</strong><br>回答が見つかりませんでした。WEBから最新情報を探しますか？</div>', unsafe_allow_html=True)
        col_yes, col_no = st.columns([0.2, 0.8])
        with col_yes:
            if st.button("🚀 検索を実行", type="primary", use_container_width=True):
                st.session_state.show_web_search_button = False
                with st.spinner("WEB情報を収集中..."):
                    profile = get_user_profile_keywords(room_data)
                    search_results = search_web_with_serper(st.session_state.pending_query, profile)
                    web_response, source_links = generate_response_from_web(st.session_state.pending_query, search_results, profile)
                    st.session_state.chat_history = [
                        {"role": "user", "content": st.session_state.pending_query + " (WEB検索)"},
                        {"role": "assistant", "content": web_response}
                    ]
                    st.session_state.last_search_links = source_links
                    st.rerun()
        with col_no:
            if st.button("キャンセル", use_container_width=True):
                st.session_state.show_web_search_button = False
                st.rerun()

    if st.session_state.last_search_links:
        st.info("📌 関連サイトを保存：")
        for i, link_data in enumerate(list(st.session_state.last_search_links)):
            with st.container(border=True):
                c1, c2, c3 = st.columns([0.7, 0.15, 0.15])
                with c1: st.markdown(f"**{link_data['title']}**")
                with c2:
                    if st.button("✅ 保存", key=f"save_indiv_{i}"):
                        raw_t, txt = fetch_url_details(link_data['url'])
                        ai_t, ai_c = classify_and_title(link_data['url'], txt, all_categories) if txt else (link_data['title'], ["未分類"])
                        save_data({"url": link_data['url'], "title": ai_t, "category": ai_c, "summary": STATUS_PENDING, "created_at": datetime.now().strftime("%Y-%m-%d")})
                        st.session_state.last_search_links.pop(i)
                        st.rerun()
                with c3:
                    if st.button("✖", key=f"skip_indiv_{i}"):
                        st.session_state.last_search_links.pop(i)
                        st.rerun()

    # 3. 検索セクション (トップページ：入力がある時のみ表示)
    st.divider()
    st.subheader("🔎 登録URLを検索")
    search_query = st.text_input("全体から検索", placeholder="タイトルや内容で検索...", label_visibility="collapsed", key="main_search")
    
    if search_query:
        q = search_query.lower()
        # ゴミ箱以外すべてから検索
        filtered_data = [item for item in room_data if CATEGORY_TRASH not in (item.get('category') if isinstance(item.get('category'), list) else [item.get('category')])]
        display_results = [item for item in filtered_data if q in item['title'].lower() or (item.get('summary') and q in item['summary'].lower())]
        
        if not display_results:
            st.info("該当するデータがありません。")
        else:
            for item in reversed(display_results):
                content_card(item)

else:
    # --- 【カテゴリーページ専用表示】 ---
    st.title(f"📂 カテゴリ: {selected_category}")
    
    # カテゴリー内検索
    search_query = st.text_input("このカテゴリー内を検索", placeholder="キーワードを入力...", key="cat_search")

    # フィルタリング
    if selected_category == CATEGORY_TRASH:
        filtered_data = [item for item in room_data if CATEGORY_TRASH in (item.get('category') if isinstance(item.get('category'), list) else [item.get('category')])]
    else:
        filtered_data = [item for item in room_data if selected_category in (item.get('category') if isinstance(item.get('category'), list) else [item.get('category')]) and CATEGORY_TRASH not in (item.get('category') if isinstance(item.get('category'), list) else [item.get('category')])]

    if search_query:
        q = search_query.lower()
        filtered_data = [item for item in filtered_data if q in item['title'].lower() or (item.get('summary') and q in item['summary'].lower())]

    display_data = list(reversed(filtered_data))

    # 一括操作パネル
    checked_urls = [item['url'] for item in display_data if st.session_state.get(f"check_{item['url']}", False)]
    if checked_urls:
        with st.expander(f"📥 一括操作 ({len(checked_urls)}件)", expanded=True):
            col_op1, col_op2, col_op3 = st.columns([0.25, 0.5, 0.25])
            with col_op1:
                if st.button("🗑️ 一括削除", use_container_width=True, type="primary"):
                    batch_delete_items(checked_urls); st.rerun()
            with col_op2:
                new_batch_cats = st.multiselect("一括カテゴリ変更", options=[c for c in all_categories if c != CATEGORY_TRASH], label_visibility="collapsed")
            with col_op3:
                if st.button("📁 実行", use_container_width=True, disabled=not new_batch_cats):
                    batch_update_categories(checked_urls, new_batch_cats); st.rerun()

    # リスト表示
    if not display_data:
        st.info("データがありません。")
    else:
        for item in display_data:
            content_card(item)