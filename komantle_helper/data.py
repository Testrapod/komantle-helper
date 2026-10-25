"""원본 API와 공개 아카이브를 읽는 데이터 계층."""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urljoin

import requests

from .archive import ROUND_PATH, atomic_write, json_bytes, read_round, validate_round
from .core import (KomantleError, RoundData, Word, KOMANTLE_URL, REQUEST_TIMEOUT,
                   SEOUL_TIME_ZONE, get_round_date, get_today_round)

MANIFEST_URL = 'https://testrapod.github.io/komantle-helper/data/manifest.json'


def fetch_round(number, *, request_get=None):
    """원본 조회. 품사 분석은 Word.pos가 요청될 때까지 시작하지 않는다."""
    if type(number) is not int or not 0 <= number <= get_today_round():
        raise KomantleError('회차는 오늘 이하의 0 이상의 정수여야 합니다.')
    try:
        response = (request_get or requests.get)(f'{KOMANTLE_URL}/{number}', timeout=REQUEST_TIMEOUT)
        if response.status_code == 404:
            raise KomantleError(f'{number}회 정보를 찾을 수 없습니다.')
        if response.status_code == 422:
            message = f'{number}회 정보를 조회할 수 없습니다.'
            try:
                payload = response.json()
                detail = payload.get('detail') if isinstance(payload, dict) else None
                if isinstance(detail, dict) and isinstance(detail.get('description'), str):
                    message += ' ' + detail['description']
            except ValueError:
                pass
            raise KomantleError(message)
        response.raise_for_status()
        data = response.json()
        answer, scores = data['key'], data['top_scores']
        if not isinstance(answer, str) or not answer or not isinstance(scores, list):
            raise ValueError()
        words = [{'word_id': 0, 'word': Word(answer), 'similarity': 100.0}]
        seen = {0}
        for rank, text, score in scores:
            if type(rank) is not int or not 1 <= rank <= 1000 or rank in seen:
                raise ValueError()
            if not isinstance(text, str) or not text or type(score) not in (int, float) or not -1 <= score <= 1:
                raise ValueError()
            seen.add(rank)
            words.append({'word_id': rank, 'word': Word(text), 'similarity': score * 100})
        return RoundData(number, words, collected_at=datetime.now(SEOUL_TIME_ZONE).isoformat())
    except requests.RequestException as error:
        raise KomantleError('꼬맨틀 서버에 연결하지 못했어요. /refresh 로 다시 시도해주세요.') from error
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, KomantleError):
            raise
        raise KomantleError('꼬맨틀 서버의 응답 형식이 올바르지 않습니다.') from error


def validate_manifest(data):
    if not isinstance(data, dict) or data.get('schema_version') != 1 or data.get('timezone') != 'Asia/Seoul' or not isinstance(data.get('rounds'), list):
        raise ValueError('지원하지 않는 데이터 목록입니다.')
    previous = -1
    for row in data['rounds']:
        if not isinstance(row, dict):
            raise ValueError("회차 목록 형식이 올바르지 않습니다.")
        number = row['round']
        match = ROUND_PATH.fullmatch(row['path'])
        if type(number) is not int or not previous < number <= get_today_round() or not match or int(match[1]) != number or row['date'] != get_round_date(number).isoformat() or row['word_count'] != 1001:
            raise ValueError('회차 목록 형식이 올바르지 않습니다.')
        previous = number
    if data.get('latest_round') != (previous if data['rounds'] else None):
        raise ValueError('최신 회차가 목록과 일치하지 않습니다.')
    return data


def round_from_archive(data, *, source):
    legacy = 'similarity_scale' not in data
    if legacy and any(abs(row['similarity']) > 1 for row in data['words'] if row['rank']):
        raise ValueError('이전 유사도 단위를 확인할 수 없습니다.')
    words = [dict(word_id=row['rank'], word=Word(row['word'], pos=row['pos']),
                  similarity=row['similarity'] * (100 if legacy and row['rank'] else 1))
             for row in data['words']]
    return RoundData(data['round'], words, source=source, collected_at=data['collected_at'])


class Repository:
    """필요한 회차만 검증한다. 캐시 쓰기 실패는 데이터 사용을 막지 않는다."""

    def __init__(self, *, archive_dir=None, cache_dir=None, request_get=None):
        self.archive_dir = Path(archive_dir) if archive_dir else None
        self.cache_dir = Path(cache_dir or Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'komantle-helper')
        self.get = request_get or requests.get
        self.manifest = None
        self.used_cached_manifest = False
        self.warning = ''

    @property
    def rounds(self):
        return [row for row in (self.manifest or {}).get('rounds', []) if row['round'] <= get_today_round()]

    def _cache(self, relative, content):
        try:
            atomic_write(self.cache_dir / relative, content)
        except OSError:
            self.warning = '데이터 캐시를 저장하지 못했어요. 현재 실행에서는 사용할 수 있어요.'

    def load_manifest(self, *, refresh=False):
        self.warning = ''
        if self.archive_dir:
            try:
                self.manifest = validate_manifest(json.loads((self.archive_dir / 'manifest.json').read_bytes()))
                return self.manifest
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise KomantleError('로컬 아카이브 목록을 읽지 못했어요. --archive-dir 경로를 확인해주세요.') from error
        cached = self.cache_dir / 'manifest.json'
        if not refresh:
            try:
                self.manifest = validate_manifest(json.loads(cached.read_bytes()))
                self.used_cached_manifest = True
                return self.manifest
            except (OSError, ValueError, KeyError, TypeError):
                pass
        try:
            response = self.get(MANIFEST_URL, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            manifest = validate_manifest(response.json())
            self.manifest = manifest
            self.used_cached_manifest = False
            self._cache('manifest.json', json_bytes(manifest))
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            try:
                self.manifest = validate_manifest(json.loads(cached.read_bytes()))
            except (OSError, ValueError, KeyError, TypeError):
                if self.manifest is None:
                    raise KomantleError('회차 목록을 불러오지 못했어요. 연결을 확인하고 /refresh 를 실행해주세요.') from error
            self.warning = '목록 갱신 실패 · 보관된 목록을 사용해요. /refresh 로 재시도할 수 있어요.'
        return self.manifest

    def load(self, number=None, *, refresh=False):
        manifest_error = None
        if self.manifest is None or refresh:
            try:
                self.load_manifest(refresh=refresh)
            except KomantleError as error:
                if self.archive_dir:
                    raise
                manifest_error = error
        if number is None:
            today = get_today_round()
            number = today if any(row['round'] == today for row in self.rounds) else self.rounds[-1]['round'] if self.rounds else today
        if type(number) is not int or not 0 <= number <= get_today_round():
            raise KomantleError('회차는 오늘 이하의 0 이상의 정수로 입력해주세요.')
        record = next((row for row in self.rounds if row['round'] == number), None)
        if record:
            relative = record['path']
            if self.archive_dir:
                try:
                    data = read_round(self.archive_dir, relative)
                    return round_from_archive(data, source='로컬 아카이브')
                except (OSError, ValueError, KeyError, TypeError) as error:
                    raise KomantleError('로컬 회차 데이터가 손상되었어요. 아카이브를 확인해주세요.') from error
            # 해시 주소의 회차 파일은 불변이다. refresh여도 정상 캐시는 재사용한다.
            try:
                data = read_round(self.cache_dir, relative)
                return round_from_archive(data, source='아카이브 캐시')
            except (OSError, ValueError, KeyError, TypeError):
                pass
            try:
                response = self.get(urljoin(MANIFEST_URL, relative), timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                content = response.content
                if hashlib.sha256(content).hexdigest() != ROUND_PATH.fullmatch(relative)[2]:
                    raise ValueError('해시 불일치')
                data = validate_round(json.loads(content))
                if data['round'] != number:
                    raise ValueError('회차 불일치')
                result = round_from_archive(data, source='공개 아카이브')
                self._cache(relative, content)
                return result
            except (requests.RequestException, ValueError, KeyError, TypeError) as error:
                raise KomantleError('회차 데이터를 검증하거나 불러오지 못했어요. /refresh 로 다시 시도해주세요.') from error
        if self.archive_dir:
            raise KomantleError('이 아카이브에 없는 회차예요. /round 로 보관된 회차를 선택해주세요.')
        try:
            result = fetch_round(number, request_get=self.get)
            if manifest_error:
                self.warning = '아카이브 연결 실패 · 원본에서 직접 불러왔어요.'
            return result
        except KomantleError as error:
            raise KomantleError(f'{error} 보관 회차는 /round 에서 확인할 수 있어요.') from error
