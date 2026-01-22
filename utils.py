import streamlit as st
import trafilatura
import json
import trafilatura.metadata
import os
import requests
from bs4 import BeautifulSoup  # 追加：HTMLクリーニング用
from dotenv import load_dotenv
from openai import OpenAI
from constants import (
    MODEL_NAME, MAX_INPUT_CHARACTERS, 
    MAX_OUTPUT_TOKENS, STATUS_PENDING, CATEGORY_TRASH, CATEGORY_PROPOSAL,
    CATEGORY_GUIDELINES, ADVISOR_SYSTEM_PROMPT,
    WEB_ADVISOR_SYSTEM_PROMPT, USER_PROFILING_PROMPT
)
from datetime import datetime, timedelta
from collections import Counter

# .envファイルを読み込む
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

# 共有AIキャッシュファイルのパス
MASTER_CACHE_FILE = "data/ai_master_cache.json"

# --- カテゴリー並び順の定義 ---
DEFAULT_START_CATEGORIES = ["ニュース", "料理", "子育て", "お出かけ", "スポーツ", "暮らし", "健康", "お金", "学び"]
DEFAULT_END_CATEGORIES = [CATEGORY_PROPOSAL, "未分類", CATEGORY_TRASH]
DEFAULT_CATEGORIES = DEFAULT_START_CATEGORIES + DEFAULT_END_CATEGORIES

# --- ユーザーID・設定管理 ---

def get_user_id():
    params = st.query_params
    return params.get("room", "default")

def get_user_data_file():
    user_id = get_user_id()
    os.makedirs("data", exist_ok=True)
    return f"data/user_data_{user_id}.json"

def load_user_config():
    user_id = get_user_id()
    config_file = f"data/config_{user_id}.json"
    user_settings = {"custom_categories": [], "rules": {}}
    
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                user_settings = json.load(f)
        except:
            pass
    
    custom_cats = user_settings.get("custom_categories", [])
    if CATEGORY_PROPOSAL not in custom_cats:
        custom_cats.append(CATEGORY_PROPOSAL)
        
    all_categories = DEFAULT_START_CATEGORIES + [c for c in custom_cats if c not in DEFAULT_CATEGORIES] + DEFAULT_END_CATEGORIES
    
    return {
        "all_categories": all_categories,
        "custom_categories": user_settings.get("custom_categories", []),
        "rules": user_settings.get("rules", {})
    }

def save_user_config(custom_categories, rules):
    user_id = get_user_id()
    config_file = f"data/config_{user_id}.json"
    os.makedirs("data", exist_ok=True)
    data_to_save = {"custom_categories": custom_categories, "rules": rules}
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(data_to_save, f, ensure_ascii=False, indent=4)

# --- 基本入出力 ---

def load_data():
    file_path = get_user_data_file()
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                if isinstance(item.get('category'), str):
                    item['category'] = [item['category']]
            return data
        except:
            return []
    return []

def save_all_data(data):
    file_path = get_user_data_file()
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def save_data(new_item):
    data = load_data()
    if isinstance(new_item.get('category'), str):
        new_item['category'] = [new_item['category']]
    data.append(new_item)
    save_all_data(data)

# --- 共有AIキャッシュ処理 ---

def load_master_cache():
    if os.path.exists(MASTER_CACHE_FILE):
        try:
            with open(MASTER_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_to_master_cache(url, ai_title, ai_cats):
    cache = load_master_cache()
    cache[url] = {
        "title": ai_title,
        "category": ai_cats,
        "updated_at": datetime.now().strftime("%Y-%m-%d")
    }
    os.makedirs(os.path.dirname(MASTER_CACHE_FILE), exist_ok=True)
    with open(MASTER_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=4)

# --- URL解析・AI処理 ---

def fetch_url_details(url):
    """
    BeautifulSoupによる不要な共通パーツの除去と、
    Trafilaturaによる本文抽出の最適化。
    """
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            # メタデータの抽出
            metadata = trafilatura.metadata.extract_metadata(downloaded)
            title = metadata.title if metadata and metadata.title else "タイトル不明"

            # BeautifulSoupによるHTMLクリーニング
            soup = BeautifulSoup(downloaded, 'html.parser')
            # 共通メニュー、ヘッダー、フッター、サイドバー、広告などを削除
            for tag in soup(['header', 'footer', 'nav', 'aside', 'script', 'style', 'iframe', 'noscript']):
                tag.decompose()
            
            # クリーニング後のHTMLから本文を抽出
            # include_links=Falseでメニュー等のリンクテキストを排除し、精度を優先
            content = trafilatura.extract(
                str(soup),
                include_comments=False,
                include_tables=True,
                no_fallback=False,
                include_links=False,
                favor_recall=False
            )
            
            # 抽出失敗時のフォールバック
            if not content:
                content = soup.get_text(separator=' ', strip=True)

            return title, content
    except Exception as e:
        st.error(f"抽出エラー: {e}")
    return None, None

def check_cache(url, data):
    for item in data:
        if item.get('url') == url: return item
    return None

def classify_and_title(url, text, categories, force_ai=False):
    config = load_user_config()
    rules = config["rules"]
    custom_rules_text = "\n".join([f"- {c}: {rules[c]}" for c in rules if c in categories])

    if not force_ai:
        master_cache = load_master_cache()
        if url in master_cache:
            cached_cats = [c for c in master_cache[url]['category'] if c in categories]
            if cached_cats: return master_cache[url]['title'], cached_cats

    truncated_text = text[:MAX_INPUT_CHARACTERS]
    prompt = f"{CATEGORY_GUIDELINES}\n\n【ルール】\n{custom_rules_text}\n\nカテゴリ候補: {', '.join(categories)}\n内容: {truncated_text}\n\n回答形式:\nTITLE: [タイトル]\nCATEGORY: [カテゴリ1, CATEGORY: [カテゴリ1, カテゴリ2]"
    
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME, messages=[{"role": "user", "content": prompt}],
            max_tokens=150, temperature=0.3
        )
        res = response.choices[0].message.content
        if "TITLE:" in res and "CATEGORY:" in res:
            title = res.split("TITLE:")[1].split("CATEGORY:")[0].strip()
            raw_category = res.split("CATEGORY:")[1].strip()
        else:
            title, raw_category = "取得したページ", "未分類"
        
        selected_cats = [c.strip() for c in raw_category.split(",")]
        category_list = [c for c in selected_cats if c in categories] or ["未分類"]
        if not force_ai: save_to_master_cache(url, title, category_list)
        return title, category_list
    except:
        return "取得したページ", ["未分類"]

# --- データ更新・再分類・削除ロジック ---

def delete_item_from_data(url):
    data = load_data()
    now_str = datetime.now().strftime("%Y-%m-%d")
    for item in data:
        if item['url'] == url:
            item['previous_category'] = item.get('category', ["未分類"])
            item['category'] = [CATEGORY_TRASH]
            item['deleted_at'] = now_str
            break
    save_all_data(data)

def update_summary_in_data(url, summary):
    data = load_data()
    for item in data:
        if item['url'] == url:
            item['summary'] = summary
            break
    save_all_data(data)

def restore_item_automatically(url):
    data = load_data()
    for item in data:
        if item['url'] == url:
            prev_cats = item.get('previous_category', ["未分類"])
            item['category'] = prev_cats
            item.pop('deleted_at', None)
            item.pop('previous_category', None)
            break
    save_all_data(data)

def delete_category_logic(target_cat):
    config = load_user_config()
    custom_cats, rules = config["custom_categories"], config["rules"]
    if target_cat in custom_cats:
        custom_cats.remove(target_cat)
        rules.pop(target_cat, None)
        save_user_config(custom_cats, rules)
        data = load_data()
        for item in data:
            if target_cat in item["category"]:
                item["category"].remove(target_cat)
                if not item["category"]: item["category"] = ["未分類"]
        save_all_data(data)

def reclassify_all_with_new_rules():
    config = load_user_config()
    data = load_data()
    for item in data:
        if CATEGORY_TRASH not in item["category"]:
            _, text = fetch_url_details(item["url"])
            if text:
                _, new_cats = classify_and_title(item["url"], text, config["all_categories"], force_ai=True)
                item["category"] = new_cats
    save_all_data(data)

def update_item_in_data(url, new_title, new_categories):
    data = load_data()
    for item in data:
        if item['url'] == url:
            item['title'], item['category'] = new_title, (new_categories if isinstance(new_categories, list) else [new_categories])
            break
    save_all_data(data)

def summarize_on_demand(url):
    data = load_data()
    item = next((i for i in data if i['url'] == url), None)
    if not item: return "データが見つかりませんでした。"

    text_to_summarize = item.get('full_content', "")
    if not text_to_summarize:
        _, text_to_summarize = fetch_url_details(url)
    
    if not text_to_summarize: return "内容を取得できませんでした。"
    
    # プロンプトの強化：共通パーツを無視する指示を追加
    prompt = (
        f"以下の内容を、ユーザーに役立つ視点で3行程度に要約してください。\n"
        f"【重要】サイトの共通メニューやショップ紹介、広告などの情報は無視し、記事のメインコンテンツのみを要約してください。\n"
        f"内容: {text_to_summarize[:MAX_INPUT_CHARACTERS]}"
    )
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME, messages=[{"role": "user", "content": prompt}],
            max_tokens=300, temperature=0.3
        )
        summary = response.choices[0].message.content.strip()
        update_summary_in_data(url, summary)
        return summary
    except:
        return "要約生成エラー"

def batch_delete_items(urls):
    data, now_str = load_data(), datetime.now().strftime("%Y-%m-%d")
    for item in data:
        if item['url'] in urls:
            item['previous_category'], item['category'], item['deleted_at'] = item['category'], [CATEGORY_TRASH], now_str
    save_all_data(data)

def batch_update_categories(urls, new_categories):
    data = load_data()
    for item in data:
        if item['url'] in urls:
            item['category'] = new_categories if isinstance(new_categories, list) else [new_categories]
    save_all_data(data)

def permanent_delete_old_items():
    data = load_data()
    if not data: return
    now = datetime.now()
    new_data = [item for item in data if not (CATEGORY_TRASH in item.get('category', []) and 
                'deleted_at' in item and now - datetime.strptime(item['deleted_at'], "%Y-%m-%d") >= timedelta(days=30))]
    if len(new_data) != len(data): save_all_data(new_data)

# --- AIアドバイザー・検索ロジック ---

def generate_proposal_from_data(user_query, room_data):
    context_text = ""
    for item in room_data:
        if CATEGORY_TRASH not in item.get('category', []):
            cats = ", ".join(item['category']) if isinstance(item['category'], list) else item['category']
            summary_info = f" 要約: {item.get('summary', '')}" if item.get('summary') != STATUS_PENDING else ""
            context_text += f"- タイトル: {item['title']}\n カテゴリ: {cats}\n URL: {item['url']}\n{summary_info}\n\n"

    full_system_prompt = ADVISOR_SYSTEM_PROMPT.format(context_text=context_text)
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "system", "content": full_system_prompt}, {"role": "user", "content": user_query}],
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"アドバイザーが席を外しています（エラー: {e}）"

def get_user_profile_keywords(room_data):
    if not room_data:
        return "一般的なトピック"

    recent_items = [item for item in room_data if CATEGORY_TRASH not in item.get('category', [])][-20:]
    titles = [item.get('title', '') for item in recent_items]
    
    if not titles:
        return "一般的なトピック"

    titles_text = "\n".join(titles)
    prompt = USER_PROFILING_PROMPT.format(titles_text=titles_text)

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50,
            temperature=0.3
        )
        profile_keywords = response.choices[0].message.content.strip()
        return profile_keywords.replace("\n", " ")
    except:
        all_cats = []
        for item in room_data:
            cats = item.get('category', [])
            if isinstance(cats, list): all_cats.extend(cats)
        common_cats = [cat for cat, count in Counter(all_cats).most_common(3)]
        return " ".join(common_cats)

def search_web_with_serper(query, profile_keywords):
    url = "https://google.serper.dev/search"
    full_query = f"{query} {profile_keywords}"
    payload = json.dumps({"q": full_query, "gl": "jp", "hl": "ja"})
    headers = {'X-API-KEY': os.getenv("SERPER_API_KEY"), 'Content-Type': 'application/json'}
    try:
        response = requests.request("POST", url, headers=headers, data=payload)
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def generate_response_from_web(user_query, search_results, profile_keywords):
    snippets = []
    source_links = []
    if "organic" in search_results:
        for result in search_results["organic"][:3]:
            title = result.get('title', '不明なタイトル')
            link = result.get('link', '#')
            snippet = result.get('snippet', '')
            snippets.append(f"- {title}: {snippet} (URL: {link})")
            source_links.append({"title": title, "url": link})
    
    web_context = "\n".join(snippets)
    full_prompt = WEB_ADVISOR_SYSTEM_PROMPT.format(
        profile_keywords=profile_keywords,
        web_context=web_context,
        user_query=user_query
    )

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": full_prompt}],
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0.7
        )
        return response.choices[0].message.content, source_links
    except Exception as e:
        return f"WEB情報の解析中にエラーが発生しました: {e}", []
    
def save_proposal_to_list(user_query, ai_response):
    """
    AIの提案内容を「提案結果」カテゴリとして保存する
    """
    short_title = (user_query[:30] + '...') if len(user_query) > 30 else user_query
    
    new_item = {
        "url": f"proposal://{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "title": f"💡回答：{short_title}",
        "category": [CATEGORY_PROPOSAL],
        "summary": STATUS_PENDING,
        "full_content": ai_response,
        "created_at": datetime.now().strftime("%Y-%m-%d")
    }
    
    save_data(new_item)
    return True