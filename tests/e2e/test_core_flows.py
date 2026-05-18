"""
Core E2E flows for BattleBugs.

Each test class covers one screen / user journey.
Tests are independent — each gets a fresh browser page (but the same live server).

Run:
    pytest tests/e2e/ -q                  # headless
    pytest tests/e2e/ --headed -q         # show browser
    pytest tests/e2e/ -k test_login -q    # single test
"""

import re
import pytest
from playwright.sync_api import expect, Page


# ── Assertion helpers ────────────────────────────────────────────────────────

def body_contains_any(page: Page, *texts: str) -> bool:
    body = page.locator('body').inner_text().lower()
    return any(t.lower() in body for t in texts)


def assert_no_error(page: Page):
    body = page.locator('body').inner_text()
    assert '500' not in body
    assert 'OperationalError' not in body
    assert 'Traceback' not in body


def re_title(pattern: str):
    return re.compile(pattern, re.IGNORECASE)


# ── Auth ────────────────────────────────────────────────────────────────────

class TestAuth:
    def test_homepage_loads(self, page, base_url):
        page.goto(base_url)
        expect(page).to_have_title(re_title('Bug Arena|Battle|BattleBugs'))

    def test_login_success(self, page, base_url):
        page.goto(f'{base_url}/login')
        page.fill('input[name="username"]', 'testuser')
        page.fill('input[name="password"]', 'Password1!')
        page.click('button[type="submit"]')
        expect(page).not_to_have_url(f'{base_url}/login')
        expect(page.locator('nav')).to_contain_text('testuser')

    def test_login_wrong_password(self, page, base_url):
        page.goto(f'{base_url}/login')
        page.fill('input[name="username"]', 'testuser')
        page.fill('input[name="password"]', 'wrongpassword')
        page.click('button[type="submit"]')
        expect(page).to_have_url(f'{base_url}/login')
        assert body_contains_any(page, 'Invalid', 'incorrect', 'wrong', 'failed')

    def test_register_duplicate_username(self, page, base_url):
        page.goto(f'{base_url}/register')
        page.fill('input[name="username"]', 'testuser')
        page.fill('input[name="email"]', 'newuniq@example.com')
        page.fill('input[name="password"]', 'Password1!')
        page.click('button[type="submit"]')
        assert body_contains_any(page, 'already', 'taken', 'exists', 'registered', 'Username')

    def test_logout(self, logged_in_page, base_url):
        page = logged_in_page
        page.goto(f'{base_url}/')
        page.locator('nav .dropdown-toggle', has_text='testuser').click()
        page.locator('a', has_text='Logout').click()
        expect(page.locator('nav')).not_to_contain_text('testuser')


# ── Bug List ────────────────────────────────────────────────────────────────

class TestBugList:
    def test_bug_list_loads(self, page, base_url):
        page.goto(f'{base_url}/bugs')
        expect(page).to_have_title(re_title('Bug'))
        assert page.locator('.bug-card').count() >= 1

    def test_search_filter(self, page, base_url):
        page.goto(f'{base_url}/bugs')
        page.fill('input[name="search"]', 'Iron Fang')
        page.click('button[type="submit"]')
        cards = page.locator('.bug-card')
        for i in range(cards.count()):
            assert 'Iron Fang' in cards.nth(i).inner_text()

    def test_tier_filter(self, page, base_url):
        page.goto(f'{base_url}/bugs')
        page.select_option('select[name="tier"]', 'ou')
        page.click('button[type="submit"]')
        assert_no_error(page)
        assert page.locator('.bug-card').count() >= 1

    def test_attack_type_filter_no_crash(self, page, base_url):
        page.goto(f'{base_url}/bugs')
        page.select_option('select[name="attack_type"]', 'piercing')
        page.click('button[type="submit"]')
        assert_no_error(page)

    def test_defense_type_filter_no_crash(self, page, base_url):
        page.goto(f'{base_url}/bugs')
        page.select_option('select[name="defense_type"]', 'hard_shell')
        page.click('button[type="submit"]')
        assert_no_error(page)

    def test_sort_by_wins(self, page, base_url):
        page.goto(f'{base_url}/bugs')
        page.select_option('select[name="sort_by"]', 'wins')
        page.click('button[type="submit"]')
        assert_no_error(page)

    def test_reset_filters(self, page, base_url):
        page.goto(f'{base_url}/bugs?tier=ou&sort_by=wins')
        page.locator('a', has_text='Reset').click()
        assert page.url == f'{base_url}/bugs'

    def test_filter_params_survive_pagination(self, page, base_url):
        page.goto(f'{base_url}/bugs?tier=ou&attack_type=piercing')
        assert_no_error(page)
        # If there's a Next page link, the params should be preserved in its href
        next_link = page.locator('a.page-link', has_text='Next')
        if next_link.count() > 0:
            href = next_link.get_attribute('href')
            assert 'attack_type=piercing' in href


# ── Bug Profile ─────────────────────────────────────────────────────────────

class TestBugProfile:
    def test_profile_loads(self, page, base_url):
        page.goto(f'{base_url}/bugs')
        page.locator('.bug-card a', has_text='View Profile').first.click()
        assert_no_error(page)

    def test_tier_tile_visible(self, page, base_url):
        page.goto(f'{base_url}/bugs?search=Iron+Fang')
        page.locator('a', has_text='View Profile').first.click()
        # OU tier tile should appear prominently
        assert page.locator('.badge', has_text='OU').count() >= 1

    def test_zu_funny_badge_visible(self, page, base_url):
        page.goto(f'{base_url}/bugs?search=Gently+Used')
        if page.locator('.bug-card').count() == 0:
            pytest.skip('No ZU bug seeded')
        page.locator('a', has_text='View Profile').first.click()
        funny_names = [
            'Certified Harmless', 'Permanent Bench', 'Participation Award',
            'Tried Its Best', 'Deeply Misunderstood', 'Gently Used', 'Moral Victory',
        ]
        body = page.locator('body').inner_text()
        assert any(name in body for name in funny_names), \
            f'No ZU funny badge found. Snippet: {body[:400]}'

    def test_profile_stat_radar_present(self, page, base_url):
        page.goto(f'{base_url}/bugs')
        page.locator('a', has_text='View Profile').first.click()
        assert_no_error(page)
        expect(page.locator('canvas#statRadar')).to_be_attached()


# ── Ecosystem ───────────────────────────────────────────────────────────────

class TestEcosystem:
    def test_ecosystem_loads(self, page, base_url):
        page.goto(f'{base_url}/ecosystem')
        expect(page).to_have_title(re_title('Ecosystem'))
        assert_no_error(page)

    def test_combat_matrix_visible(self, page, base_url):
        page.goto(f'{base_url}/ecosystem')
        expect(page.locator('h4', has_text='Combat Type Matchup Matrix')).to_be_visible()
        # 9 attack types → 9 data rows
        assert page.locator('table').first.locator('tbody tr').count() >= 9

    def test_size_matrix_visible(self, page, base_url):
        page.goto(f'{base_url}/ecosystem')
        expect(page.locator('h4', has_text='Size Matchup Matrix')).to_be_visible()

    def test_size_matrix_has_5_rows(self, page, base_url):
        page.goto(f'{base_url}/ecosystem')
        # Find the second table (size matrix) — combat matrix is first
        tables = page.locator('table')
        size_table = tables.nth(1)
        assert size_table.locator('tbody tr').count() == 5

    def test_species_network_section(self, page, base_url):
        page.goto(f'{base_url}/ecosystem')
        expect(page.locator('h4', has_text='Species Predator')).to_be_visible()


# ── Battles ─────────────────────────────────────────────────────────────────

class TestBattles:
    def test_battle_list_loads(self, page, base_url):
        page.goto(f'{base_url}/battles')
        assert_no_error(page)

    def test_new_battle_requires_login(self, page, base_url):
        page.goto(f'{base_url}/battle/new')
        assert '/login' in page.url

    def test_new_battle_page_loads_when_authenticated(self, logged_in_page, base_url):
        page = logged_in_page
        page.goto(f'{base_url}/battle/new')
        assert_no_error(page)


# ── Navigation smoke tests ───────────────────────────────────────────────────

class TestNavigation:
    @pytest.mark.parametrize('path,expected_text', [
        ('/bugs',        'Gladiators'),
        ('/insectidex',  'Insectidex'),
        ('/leaderboards','Leaderboard'),
        ('/ecosystem',   'Ecosystem'),
        ('/battles',     'Battle'),
        ('/tournaments', 'Tournament'),
    ])
    def test_nav_page_loads(self, page, base_url, path, expected_text):
        page.goto(f'{base_url}{path}')
        assert_no_error(page)
        assert expected_text.lower() in page.locator('body').inner_text().lower()
