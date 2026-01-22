import streamlit as st
from utils import (
    summarize_on_demand, 
    update_summary_in_data, 
    update_item_in_data, 
    delete_item_from_data,
    restore_item_automatically,
    load_user_config,
    save_user_config,
    delete_category_logic,
    reclassify_all_with_new_rules,
    DEFAULT_CATEGORIES
)
from constants import STATUS_PENDING, CATEGORY_TRASH, CATEGORY_PROPOSAL

def content_card(item):
    """
    通常時はチェックボックス付きのスマートな1行リスト。
    編集時のみ横幅いっぱいのカードに切り転換。
    """
    url_id = item['url']
    item_cats = item.get('category', [])
    if isinstance(item_cats, str):
        item_cats = [item_cats]
    
    is_in_trash = (CATEGORY_TRASH in item_cats)
    is_proposal = (CATEGORY_PROPOSAL in item_cats)
    
    # ユーザー固有の設定をロード（表示・選択用）
    config = load_user_config()
    all_categories = config["all_categories"]
    
    # --- 状態管理キーの初期化 ---
    edit_mode_key = f"edit_all_{url_id}"
    if edit_mode_key not in st.session_state:
        st.session_state[edit_mode_key] = False

    check_key = f"check_{url_id}"
    if check_key not in st.session_state:
        st.session_state[check_key] = False

    # --- 1. ワイド編集モード ---
    if st.session_state[edit_mode_key]:
        with st.container(border=True):
            st.markdown("### 📝 データの修正")
            
            new_title = st.text_input("タイトル", value=item['title'], key=f"edit_t_{url_id}")
            
            valid_options = [c for c in all_categories if c != CATEGORY_TRASH]
            new_cats = st.multiselect(
                "カテゴリー（複数選択可）", 
                options=valid_options, 
                default=[c for c in item_cats if c in valid_options],
                key=f"edit_c_{url_id}"
            )
            
            raw_summary = item.get('summary', "")
            clean_summary = raw_summary.replace("AI要約:", "").strip() if raw_summary != STATUS_PENDING else ""
            new_summary = st.text_area("要約・メモ", value=clean_summary, key=f"edit_s_{url_id}", height=180)
            
            btn_col1, btn_col2 = st.columns([0.2, 0.8])
            with btn_col1:
                if st.button("保存", key=f"save_all_{url_id}", use_container_width=True, type="primary"):
                    save_cats = new_cats if new_cats else ["未分類"]
                    update_item_in_data(url_id, new_title, save_cats)
                    update_summary_in_data(url_id, new_summary)
                    st.session_state[edit_mode_key] = False
                    st.rerun()
            with btn_col2:
                if st.button("キャンセル", key=f"cancel_all_{url_id}"):
                    st.session_state[edit_mode_key] = False
                    st.rerun()
        return

    # --- 2. 通常表示モード ---
    col_check, col_main, col_detail = st.columns([0.07, 0.73, 0.2])
    
    with col_check:
        st.checkbox("選択", key=check_key, label_visibility="collapsed")
        
    with col_main:
        prefix = "🗑️ " if is_in_trash else ("🪄 " if is_proposal else "📄 ")
        
        # 【修正：提案結果の場合はボタン、それ以外は外部リンク】
        if is_proposal:
            if st.button(f"{prefix} {item['title']}", key=f"title_link_{url_id}", help="クリックして内容を表示"):
                st.session_state.view_full_content = url_id
                st.rerun()
        else:
            st.markdown(
                f"<div style='margin-top: 6px;'>{prefix} "
                f"<a href='{item['url']}' target='_blank' style='text-decoration:none; font-weight:bold; color:#1f77b4;'>"
                f"{item['title']}</a></div>", 
                unsafe_allow_html=True
            )
    
    with col_detail:
        menu = st.popover("詳細", use_container_width=True)

    with menu:
        if item_cats:
            # カテゴリジャンプボタン
            for cat in item_cats:
                if st.button(f"📁 {cat} ", key=f"jump_{url_id}_{cat}", use_container_width=True):
                    st.session_state["selected_category"] = cat
                    st.rerun()

        raw_summary = item.get('summary', STATUS_PENDING)
        if not is_proposal: # 提案結果以外は要約機能を表示
            if raw_summary == STATUS_PENDING:
                st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
                if st.button("✨ 要約を生成", key=f"gen_{url_id}", type="primary", use_container_width=True):
                    with st.spinner("解析中..."):
                        res = summarize_on_demand(url_id)
                        update_summary_in_data(url_id, f"AI要約:{res}")
                        st.rerun()
            else:
                is_ai = raw_summary.startswith("AI要約:")
                bg_color, border_color = ("#f0f2f6", "#1f77b4") if is_ai else ("#fef9e7", "#f39c12")
                label = "<b>✨ AI要約:</b><br>" if is_ai else "<b>📝 メモ:</b><br>"
                content = raw_summary.replace("AI要約:", "").strip()

                st.markdown(
                    f"<div style='font-size: 0.85em; background:{bg_color}; padding:10px; border-radius:8px; "
                    f"border-left:4px solid {border_color}; margin-top: 8px; margin-bottom: 3px;'>"
                    f"{label}{content}</div>", 
                    unsafe_allow_html=True
                )

        st.divider()

        if is_in_trash:
            if st.button("元の場所に戻す", key=f"res_{url_id}", use_container_width=True):
                restore_item_automatically(url_id)
                st.rerun()
        else:
            c1, c2 = st.columns(2)
            with c1:
                if st.button("編集", key=f"edit_btn_{url_id}", use_container_width=True):
                    st.session_state[edit_mode_key] = True
                    st.rerun()
            with c2:
                if st.button("🗑️", key=f"del_btn_{url_id}", use_container_width=True, help="ごみ箱へ移動"):
                    delete_item_from_data(url_id)
                    st.rerun()

def sidebar_component():
    """サイドバー：プルダウン式カテゴリー選択を実装。"""
    with st.sidebar:
        # --- 入力（検索機能）を無効化するためのCSS ---
        st.markdown("""
            <style>
            /* 入力カーソルを非表示にし、ポインターイベントを調整して選択専用に見せる */
            div[data-baseweb="select"] input {
                caret-color: transparent !important;
                cursor: pointer !important;
            }
            </style>
        """, unsafe_allow_html=True)

        # --- 1. 最上位メニュー ---
        st.markdown("### 🏠 メインメニュー")
        if st.button("✨ URLの追加とアドバイザー", key="side_top_nav"):
            st.session_state["selected_category"] = "トップページ"
            st.rerun()
            
        st.divider()

        # --- 2. カテゴリー選択（プルダウン形式） ---
        st.markdown("### 📂 カテゴリー表示")
        
        config = load_user_config()
        all_cats = config["all_categories"]
        
        default_label = "ーーーー"
        options = [default_label] + all_cats

        # コールバック関数：選択された瞬間にページ遷移を実行し、表示をリセットする
        def handle_cat_change():
            selected = st.session_state["category_selector_internal"]
            if selected != default_label:
                st.session_state["selected_category"] = selected
                # セレクトボックス自体の値を「ーーーー」に強制リセット
                st.session_state["category_selector_internal"] = default_label

        st.selectbox(
            "表示するフォルダを選択",
            options=options,
            index=0,
            key="category_selector_internal",
            on_change=handle_cat_change
        )
        
        st.divider()
        
        # --- 3. カテゴリーの新規作成 ---
        st.subheader("🆕 カテゴリーを作る")
        with st.expander("新しいルールを追加"):
            new_cat_name = st.text_input("カテゴリー名", placeholder="例: キャンプ", key="new_cat_input")
            new_cat_rule = st.text_area("AIへの分類ルール", placeholder="例: キャンプ道具のレビューなど", key="new_rule_input")
            
            if st.button("作成する", use_container_width=True, type="primary"):
                if new_cat_name:
                    if new_cat_name in all_cats:
                        st.error("その名前は既に存在します。")
                    else:
                        custom_cats = config["custom_categories"]
                        user_rules = config["rules"]
                        custom_cats.append(new_cat_name)
                        user_rules[new_cat_name] = new_cat_rule
                        save_user_config(custom_cats, user_rules)
                        st.session_state["rule_changed"] = True
                        st.success(f"「{new_cat_name}」を作成しました")
                        st.rerun()

        # --- 4. 既存カテゴリーの修正・削除 ---
        custom_cats = config["custom_categories"]
        if custom_cats:
            st.subheader("🔧 独自カテゴリーを直す")
            with st.expander("登録済みルールの編集・削除"):
                edit_target = st.selectbox("修正するカテゴリーを選択", options=custom_cats, key="edit_target_select")
                
                if edit_target:
                    user_rules = config["rules"]
                    current_rule = user_rules.get(edit_target, "")
                    updated_rule = st.text_area("ルールの修正", value=current_rule, key=f"edit_rule_{edit_target}")
                    
                    col_edit1, col_edit2 = st.columns(2)
                    with col_edit1:
                        if st.button("修正を保存", use_container_width=True, key=f"save_edit_{edit_target}"):
                            user_rules[edit_target] = updated_rule
                            save_user_config(custom_cats, user_rules)
                            st.session_state["rule_changed"] = True
                            st.success("ルールを更新しました")
                            st.rerun()
                    with col_edit2:
                        if st.button("🗑️ 削除", use_container_width=True, key=f"del_edit_{edit_target}"):
                            delete_category_logic(edit_target)
                            st.rerun()
        
        st.divider()

        # --- 5. 再分類実行 ---
        if st.session_state.get("rule_changed", False):
            st.warning("⚠️ ルールが変更されました。")
            if st.button("✨ 全アイテムを再分類", use_container_width=True, type="primary"):
                with st.spinner("AIが再判定中..."):
                    reclassify_all_with_new_rules()
                    st.session_state["rule_changed"] = False
                    st.success("再分類が完了しました！")
                    st.rerun()