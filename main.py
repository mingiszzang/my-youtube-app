import re
from collections import Counter
from urllib.parse import urlparse, parse_qs

import pandas as pd
import plotly.express as px
import requests
import streamlit as st


# =========================================================
# 기본 설정
# =========================================================
st.set_page_config(
    page_title="유튜브 댓글 분석",
    page_icon="💬",
    layout="wide",
)

DEFAULT_URL = "https://youtu.be/d95J8yzvjbQ?si=LfL5DLwCL8Pk077r"
EXAMPLE_2_URL = "https://youtu.be/I9vK5EVTt0U?si=NEZ8L7MRuNvrzINa"

YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3/commentThreads"


# =========================================================
# 유튜브 링크에서 영상 ID 추출
# =========================================================
def extract_video_id(url: str) -> str | None:
    """
    유튜브 주소에서 11자리 영상 ID를 추출합니다.

    처리 가능한 주소 예시
    - https://youtu.be/영상ID
    - https://www.youtube.com/watch?v=영상ID
    - https://youtube.com/shorts/영상ID
    - https://youtube.com/embed/영상ID
    """

    if not url:
        return None

    url = url.strip()

    try:
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.lower()
        path = parsed_url.path.strip("/")

        # youtu.be 형식의 짧은 주소
        if domain in {"youtu.be", "www.youtu.be"}:
            video_id = path.split("/")[0]

        # youtube.com 형식의 주소
        elif domain in {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com",
        }:
            # 일반 영상 주소
            if path == "watch":
                video_id = parse_qs(parsed_url.query).get("v", [None])[0]

            # Shorts, 라이브, 임베드 주소
            elif path.startswith(("shorts/", "embed/", "live/")):
                parts = path.split("/")
                video_id = parts[1] if len(parts) >= 2 else None

            else:
                video_id = None

        else:
            video_id = None

        # 유튜브 영상 ID가 올바른 11자리인지 확인합니다.
        if video_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            return video_id

    except (ValueError, IndexError):
        return None

    return None


# =========================================================
# YouTube API로 댓글 가져오기
# =========================================================
def fetch_youtube_comments(video_id: str, api_key: str) -> list[dict]:
    """
    YouTube Data API v3를 이용해
    최상위 댓글을 최대 100개 가져옵니다.
    """

    params = {
        "part": "snippet",
        "videoId": video_id,
        "maxResults": 100,
        "order": "relevance",
        "textFormat": "plainText",
        "key": api_key,
    }

    response = requests.get(
        YOUTUBE_API_URL,
        params=params,
        timeout=15,
    )

    # API가 오류를 반환한 경우 오류 원인을 확인합니다.
    if response.status_code != 200:
        error_reason = ""
        error_message = ""

        try:
            error_data = response.json().get("error", {})
            error_message = error_data.get("message", "")

            errors = error_data.get("errors", [])
            if errors:
                error_reason = errors[0].get("reason", "")

        except ValueError:
            pass

        if error_reason == "commentsDisabled":
            raise ValueError(
                "이 영상은 댓글 사용이 중지되어 있어 댓글을 가져올 수 없습니다."
            )

        if error_reason in {"videoNotFound", "forbidden"}:
            raise ValueError(
                "영상을 찾을 수 없습니다. 비공개 또는 삭제된 영상인지 확인해 주세요."
            )

        if error_reason in {
            "keyInvalid",
            "quotaExceeded",
            "dailyLimitExceeded",
            "accessNotConfigured",
        }:
            raise ValueError(
                "YouTube API 설정에 문제가 있습니다. "
                "API 키 또는 사용량 한도를 확인해 주세요."
            )

        raise ValueError(
            error_message
            or "YouTube에서 댓글을 가져오는 중 오류가 발생했습니다."
        )

    data = response.json()
    comments = []

    # 각 댓글 스레드에서 최상위 댓글 정보를 꺼냅니다.
    for item in data.get("items", []):
        try:
            snippet = item["snippet"]["topLevelComment"]["snippet"]

            comments.append(
                {
                    "댓글": snippet.get("textOriginal", ""),
                    "좋아요": int(snippet.get("likeCount", 0)),
                }
            )

        except (KeyError, TypeError, ValueError):
            continue

    # 좋아요가 많은 순서로 정렬합니다.
    comments.sort(
        key=lambda comment: comment["좋아요"],
        reverse=True,
    )

    # 표에 표시할 순위를 추가합니다.
    for rank, comment in enumerate(comments, start=1):
        comment["순위"] = rank

    return comments


# =========================================================
# 댓글 단어 빈도 분석
# =========================================================
def count_top_words(comments: list[dict], top_n: int = 20) -> pd.DataFrame:
    """
    전체 댓글을 단어로 나눈 뒤 자주 등장한 단어를 계산합니다.

    - 영문은 소문자로 통일합니다.
    - 한글, 영문, 숫자를 단어로 인식합니다.
    - 한 글자 단어는 제외합니다.
    - 숫자로만 이루어진 단어는 제외합니다.
    """

    # 모든 댓글을 하나의 긴 문자열로 합칩니다.
    all_text = " ".join(
        comment.get("댓글", "")
        for comment in comments
    )

    # 한글, 영문, 숫자로 이루어진 단어를 찾습니다.
    words = re.findall(
        r"[가-힣A-Za-z0-9]+",
        all_text.lower(),
    )

    filtered_words = []

    for word in words:
        # 한 글자짜리 단어는 제외합니다.
        if len(word) <= 1:
            continue

        # 숫자로만 이루어진 값도 제외합니다.
        if word.isdigit():
            continue

        filtered_words.append(word)

    # 가장 자주 등장한 단어를 지정된 개수만큼 계산합니다.
    word_counts = Counter(filtered_words).most_common(top_n)

    return pd.DataFrame(
        word_counts,
        columns=["단어", "빈도"],
    )


# =========================================================
# 예시 버튼을 눌렀을 때 입력창 주소 변경
# =========================================================
def set_example_url(url: str):
    st.session_state.youtube_url = url

    # 다른 영상을 선택하면 이전 분석 결과를 지웁니다.
    st.session_state.comments = None
    st.session_state.analyzed_video_id = None


# =========================================================
# 세션 상태 초기값
# =========================================================
if "youtube_url" not in st.session_state:
    st.session_state.youtube_url = DEFAULT_URL

if "comments" not in st.session_state:
    st.session_state.comments = None

if "analyzed_video_id" not in st.session_state:
    st.session_state.analyzed_video_id = None


# =========================================================
# 화면 구성
# =========================================================
st.title("💬 유튜브 댓글 분석")

st.write(
    "유튜브 영상 링크를 입력하면 댓글을 최대 100개까지 가져와 "
    "댓글 내용과 자주 등장한 단어를 분석합니다."
)

st.subheader("예시 영상")

# 예시 버튼 두 개를 가로로 배치합니다.
example_col1, example_col2 = st.columns(2)

with example_col1:
    st.button(
        "예시 1 · 딥마인드 다큐(영어 댓글)",
        use_container_width=True,
        on_click=set_example_url,
        args=(DEFAULT_URL,),
    )

with example_col2:
    st.button(
        "예시 2 · 2002 월드컵 추억(한국어 댓글)",
        use_container_width=True,
        on_click=set_example_url,
        args=(EXAMPLE_2_URL,),
    )


# 링크 입력창과 실행 버튼을 하나의 form으로 묶습니다.
with st.form("youtube_comment_form"):
    st.text_input(
        "유튜브 영상 링크",
        key="youtube_url",
        placeholder="https://www.youtube.com/watch?v=...",
    )

    submitted = st.form_submit_button(
        "댓글 가져오기",
        type="primary",
        use_container_width=True,
    )


# =========================================================
# 댓글 가져오기 실행
# =========================================================
if submitted:
    video_id = extract_video_id(st.session_state.youtube_url)

    if video_id is None:
        st.session_state.comments = None
        st.session_state.analyzed_video_id = None

        st.error(
            "올바른 유튜브 영상 링크를 입력해 주세요. "
            "`youtu.be` 주소와 `youtube.com/watch` 주소를 사용할 수 있습니다."
        )

    else:
        # Streamlit Cloud Secrets에서 API 키를 불러옵니다.
        try:
            api_key = st.secrets["YOUTUBE_API_KEY"]
        except (KeyError, FileNotFoundError):
            api_key = None

        if not api_key:
            st.session_state.comments = None
            st.session_state.analyzed_video_id = None

            st.error(
                "YouTube API 키가 설정되지 않았습니다. "
                "Streamlit Cloud의 Secrets에 "
                "`YOUTUBE_API_KEY`를 등록해 주세요."
            )

        else:
            try:
                with st.spinner("유튜브 댓글을 가져오고 있습니다..."):
                    comments = fetch_youtube_comments(
                        video_id=video_id,
                        api_key=api_key,
                    )

                st.session_state.comments = comments
                st.session_state.analyzed_video_id = video_id

                if comments:
                    st.success("댓글을 성공적으로 가져왔습니다.")
                else:
                    st.info(
                        "가져올 수 있는 공개 댓글이 없습니다. "
                        "댓글이 없거나 댓글 공개가 제한된 영상일 수 있습니다."
                    )

            except requests.exceptions.Timeout:
                st.session_state.comments = None
                st.session_state.analyzed_video_id = None

                st.error(
                    "YouTube 서버의 응답이 늦어지고 있습니다. "
                    "잠시 후 다시 시도해 주세요."
                )

            except requests.exceptions.RequestException:
                st.session_state.comments = None
                st.session_state.analyzed_video_id = None

                st.error(
                    "YouTube 서버에 연결하지 못했습니다. "
                    "인터넷 연결 상태를 확인한 뒤 다시 시도해 주세요."
                )

            except ValueError as error:
                st.session_state.comments = None
                st.session_state.analyzed_video_id = None

                st.error(str(error))

            except Exception:
                st.session_state.comments = None
                st.session_state.analyzed_video_id = None

                st.error(
                    "댓글을 가져오는 중 예상하지 못한 오류가 발생했습니다. "
                    "영상 링크와 API 설정을 확인해 주세요."
                )


# =========================================================
# 분석 결과 표시
# =========================================================
comments = st.session_state.comments

if comments is not None:
    st.divider()
    st.header("분석 결과")

    # 가져온 댓글 개수를 큰 지표 카드로 표시합니다.
    st.metric(
        label="가져온 댓글 수",
        value=f"{len(comments):,}개",
    )

    if comments:
        # -------------------------------------------------
        # 자주 등장한 단어 분석
        # -------------------------------------------------
        st.subheader("자주 등장한 단어")

        word_df = count_top_words(
            comments=comments,
            top_n=20,
        )

        if not word_df.empty:
            # Plotly에서 가로 막대그래프를 만들기 위해
            # 빈도가 작은 단어부터 배치합니다.
            # 그러면 빈도가 가장 높은 단어가 그래프 위쪽에 표시됩니다.
            chart_df = word_df.sort_values(
                "빈도",
                ascending=True,
            )

            fig = px.bar(
                chart_df,
                x="빈도",
                y="단어",
                orientation="h",
                text="빈도",
                labels={
                    "빈도": "등장 횟수",
                    "단어": "",
                },
            )

            # 막대 바깥쪽에 빈도 숫자를 표시합니다.
            fig.update_traces(
                textposition="outside",
                cliponaxis=False,
            )

            # 그래프 높이와 여백을 조정합니다.
            fig.update_layout(
                height=620,
                margin=dict(
                    l=20,
                    r=50,
                    t=20,
                    b=20,
                ),
                yaxis={
                    "categoryorder": "total ascending",
                },
                showlegend=False,
            )

            st.plotly_chart(
                fig,
                use_container_width=True,
                key="word_frequency_chart",
            )

            st.caption(
                "전체 댓글을 공백과 문장부호를 기준으로 나눈 뒤, "
                "한 글자 단어와 숫자로만 이루어진 값은 제외했습니다."
            )

        else:
            st.info(
                "댓글에서 분석할 수 있는 단어를 찾지 못했습니다."
            )

        # -------------------------------------------------
        # 댓글 목록
        # -------------------------------------------------
        st.subheader("댓글 목록")

        comments_df = pd.DataFrame(comments)

        comments_df = comments_df[
            [
                "순위",
                "좋아요",
                "댓글",
            ]
        ]

        st.dataframe(
            comments_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "순위": st.column_config.NumberColumn(
                    "순위",
                    format="%d위",
                    width="small",
                ),
                "좋아요": st.column_config.NumberColumn(
                    "좋아요",
                    format="%d",
                    width="small",
                ),
                "댓글": st.column_config.TextColumn(
                    "댓글 원문",
                    width="large",
                ),
            },
        )

        st.caption(
            "댓글은 YouTube API에서 relevance 기준으로 최대 100개를 가져온 뒤, "
            "좋아요 수가 많은 순서로 다시 정렬했습니다."
        )
