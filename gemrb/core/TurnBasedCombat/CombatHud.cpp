// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#include "TurnBasedCombat/CombatHud.h"

#include "damages.h"

#include "GameData.h"
#include "Spell.h"

#include "Game.h"
#include "Interface.h"
#include "Map.h"
#include "RNG.h"
#include "Audio/Playback.h"

#include "GUI/GameControl.h"
#include "GUI/TextSystem/Font.h"
#include "Scriptable/Actor.h"
#include "TurnBasedCombat/CombatDirector.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <functional>

namespace GemRB {

const Color CombatHud::Theme::panel(14, 11, 9, 215);
const Color CombatHud::Theme::border(158, 118, 66, 255);
const Color CombatHud::Theme::borderDark(64, 44, 24, 255);
const Color CombatHud::Theme::text(232, 222, 196, 255);
const Color CombatHud::Theme::textDim(160, 148, 124, 255);
const Color CombatHud::Theme::hit(120, 220, 96, 255);
const Color CombatHud::Theme::miss(226, 82, 60, 255);
const Color CombatHud::Theme::crit(255, 208, 72, 255);
const Color CombatHud::Theme::fumble(200, 52, 40, 255);

// ------------------------------------------------------------------------------------------
// a little vector maths for the die

namespace {

struct V3 {
	float x = 0, y = 0, z = 0;
};
V3 operator+(V3 a, V3 b) { return { a.x + b.x, a.y + b.y, a.z + b.z }; }
V3 operator-(V3 a, V3 b) { return { a.x - b.x, a.y - b.y, a.z - b.z }; }
V3 operator*(V3 a, float s) { return { a.x * s, a.y * s, a.z * s }; }
float Dot(V3 a, V3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
V3 Cross(V3 a, V3 b) { return { a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x }; }
V3 Normalize(V3 a)
{
	float l = std::sqrt(Dot(a, a));
	return l > 0 ? a * (1.0f / l) : a;
}

struct Quat {
	float w = 1, x = 0, y = 0, z = 0;
};
Quat operator*(Quat a, Quat b)
{
	return { a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z,
		 a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
		 a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
		 a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w };
}
Quat AxisAngle(V3 axis, float angle)
{
	axis = Normalize(axis);
	float s = std::sin(angle / 2);
	return { std::cos(angle / 2), axis.x * s, axis.y * s, axis.z * s };
}
V3 Rotate(const Quat& q, V3 v)
{
	V3 u { q.x, q.y, q.z };
	V3 t = Cross(u, v) * 2.0f;
	return v + t * q.w + Cross(u, t);
}
// the rotation whose matrix has these rows (it maps a to x, b to y, c to z)
Quat FromRows(V3 a, V3 b, V3 c)
{
	float m00 = a.x, m01 = a.y, m02 = a.z;
	float m10 = b.x, m11 = b.y, m12 = b.z;
	float m20 = c.x, m21 = c.y, m22 = c.z;
	Quat q;
	float trace = m00 + m11 + m22;
	if (trace > 0) {
		float s = std::sqrt(trace + 1.0f) * 2;
		q = { 0.25f * s, (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s };
	} else if (m00 > m11 && m00 > m22) {
		float s = std::sqrt(1.0f + m00 - m11 - m22) * 2;
		q = { (m21 - m12) / s, 0.25f * s, (m01 + m10) / s, (m02 + m20) / s };
	} else if (m11 > m22) {
		float s = std::sqrt(1.0f + m11 - m00 - m22) * 2;
		q = { (m02 - m20) / s, (m01 + m10) / s, 0.25f * s, (m12 + m21) / s };
	} else {
		float s = std::sqrt(1.0f + m22 - m00 - m11) * 2;
		q = { (m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25f * s };
	}
	return q;
}
Quat Slerp(Quat a, Quat b, float t)
{
	float d = a.w * b.w + a.x * b.x + a.y * b.y + a.z * b.z;
	if (d < 0) {
		b = { -b.w, -b.x, -b.y, -b.z };
		d = -d;
	}
	float wa, wb;
	if (d > 0.9995f) {
		wa = 1 - t;
		wb = t;
	} else {
		float th = std::acos(d);
		float s = std::sin(th);
		wa = std::sin((1 - t) * th) / s;
		wb = std::sin(t * th) / s;
	}
	Quat q { a.w * wa + b.w * wb, a.x * wa + b.x * wb, a.y * wa + b.y * wb, a.z * wa + b.z * wb };
	float l = std::sqrt(q.w * q.w + q.x * q.x + q.y * q.y + q.z * q.z);
	return { q.w / l, q.x / l, q.y / l, q.z / l };
}

struct Face {
	std::array<int, 3> v {};
	V3 normal;
	V3 center;
	V3 right; // the number's x and up on the face
	V3 up;
	int number = 0;
	Quat rest; // the orientation that shows this face upright to the viewer
};

struct Mesh {
	std::array<V3, 12> v;
	std::array<Face, 20> faces;
	std::array<int, 21> faceOfNumber {};
};

const Mesh& D20()
{
	static Mesh mesh = [] {
		Mesh m;
		const float p = (1.0f + std::sqrt(5.0f)) / 2;
		const V3 raw[12] = { { 0, 1, p }, { 0, -1, p }, { 0, 1, -p }, { 0, -1, -p }, { 1, p, 0 }, { -1, p, 0 },
				     { 1, -p, 0 }, { -1, -p, 0 }, { p, 0, 1 }, { -p, 0, 1 }, { p, 0, -1 }, { -p, 0, -1 } };
		auto edge = [&](int a, int b) {
			V3 d = raw[a] - raw[b];
			return std::abs(Dot(d, d) - 4.0f) < 0.01f;
		};
		size_t count = 0;
		for (int i = 0; i < 12; ++i) {
			for (int j = i + 1; j < 12; ++j) {
				for (int k = j + 1; k < 12; ++k) {
					if (!edge(i, j) || !edge(j, k) || !edge(i, k) || count >= 20) continue;
					m.faces[count++].v = { i, j, k };
				}
			}
		}
		for (int i = 0; i < 12; ++i) {
			m.v[i] = Normalize(raw[i]);
		}
		for (Face& f : m.faces) {
			V3 a = m.v[f.v[0]], b = m.v[f.v[1]], c = m.v[f.v[2]];
			f.center = (a + b + c) * (1.0f / 3);
			f.normal = Normalize(Cross(b - a, c - a));
			if (Dot(f.normal, f.center) < 0) {
				std::swap(f.v[1], f.v[2]);
				f.normal = f.normal * -1.0f;
			}
			f.up = Normalize(m.v[f.v[0]] - f.center);
			f.right = Cross(f.up, f.normal);
			f.rest = FromRows(f.right, f.up, f.normal);
		}
		// opposite faces add up to 21, like a real die
		int next = 1;
		for (Face& f : m.faces) {
			if (f.number) continue;
			f.number = next;
			for (Face& o : m.faces) {
				if (!o.number && Dot(o.normal, f.normal) < -0.99f) {
					o.number = 21 - next;
					break;
				}
			}
			++next;
		}
		for (size_t i = 0; i < m.faces.size(); ++i) {
			m.faceOfNumber[m.faces[i].number] = static_cast<int>(i);
		}
		return m;
	}();
	return mesh;
}

// stroke glyphs: rectangles in a box 0.6 wide and 1 high (y down)
struct Seg {
	float x0, y0, x1, y1;
};
constexpr float GW = 0.6f;
constexpr float GT = 0.15f;
constexpr float GADV = GW + 0.2f;
const Seg SEGS[7] = {
	{ 0, 0, GW, GT }, // a top
	{ GW - GT, 0, GW, 0.5f + GT / 2 }, // b top right
	{ GW - GT, 0.5f - GT / 2, GW, 1 }, // c bottom right
	{ 0, 1 - GT, GW, 1 }, // d bottom
	{ 0, 0.5f - GT / 2, GT, 1 }, // e bottom left
	{ 0, 0, GT, 0.5f + GT / 2 }, // f top left
	{ 0, 0.5f - GT / 2, GW, 0.5f + GT / 2 } // g middle
};
const uint8_t DIGITS[10] = { 0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f };

std::vector<Seg> StrokeGlyph(char c)
{
	std::vector<Seg> out;
	if (c >= '0' && c <= '9') {
		uint8_t mask = DIGITS[c - '0'];
		for (int i = 0; i < 7; ++i) {
			if (mask & (1 << i)) out.push_back(SEGS[i]);
		}
	} else if (c == '+') {
		out.push_back({ 0, 0.5f - GT / 2, GW, 0.5f + GT / 2 });
		out.push_back({ GW / 2 - GT / 2, 0.2f, GW / 2 + GT / 2, 0.8f });
	} else if (c == '-') {
		out.push_back({ 0.05f, 0.5f - GT / 2, GW - 0.05f, 0.5f + GT / 2 });
	} else if (c == '=') {
		out.push_back({ 0, 0.33f - GT / 2, GW, 0.33f + GT / 2 });
		out.push_back({ 0, 0.67f - GT / 2, GW, 0.67f + GT / 2 });
	}
	return out;
}

float Advance(char c)
{
	return c == ' ' ? 0.35f : GADV;
}

Color Mix(const Color& a, const Color& b, float t)
{
	t = Clamp(t, 0.0f, 1.0f);
	return Color(uint8_t(a.r + (b.r - a.r) * t), uint8_t(a.g + (b.g - a.g) * t), uint8_t(a.b + (b.b - a.b) * t), uint8_t(a.a + (b.a - a.a) * t));
}

Color Faded(Color c, float alpha)
{
	c.a = uint8_t(Clamp(c.a * alpha, 0.0f, 255.0f));
	return c;
}

// the attack die and the save die share this bone; a save stains it once the face has landed
const Color kDieBone(226, 212, 176, 255);

void PushTri(std::vector<float>& v, std::vector<Color>& col, float ax, float ay, float bx, float by, float cx, float cy, const Color& c)
{
	v.insert(v.end(), { ax, ay, bx, by, cx, cy });
	col.insert(col.end(), { c, c, c });
}

float Smooth(float t)
{
	t = Clamp(t, 0.0f, 1.0f);
	return t * t * (3 - 2 * t);
}

}

// ------------------------------------------------------------------------------------------
// drawing kit

Holder<Font> CombatHud::HudFont()
{
	static Holder<Font> font;
	if (!font) font = core->GetFont(ResRef("FONTDLG"));
	if (!font) font = core->GetTextFont();
	return font;
}

void CombatHud::DrawPanel(const Region& r, float alpha)
{
	VideoDriver->DrawRect(r, Faded(Theme::panel, alpha), true, BlitFlags::BLENDED);
	VideoDriver->DrawRect(r, Faded(Theme::borderDark, alpha), false, BlitFlags::BLENDED);
	Region inner(r.x + 1, r.y + 1, r.w - 2, r.h - 2);
	VideoDriver->DrawRect(inner, Faded(Theme::border, alpha), false, BlitFlags::BLENDED);
	Region inner2(r.x + 3, r.y + 3, r.w - 6, r.h - 6);
	VideoDriver->DrawRect(inner2, Faded(Theme::borderDark, alpha * 0.8f), false, BlitFlags::BLENDED);
	// bronze studs in the corners
	const Color stud = Faded(Theme::border, alpha);
	for (const Point& p : { Point(r.x, r.y), Point(r.x + r.w - 5, r.y), Point(r.x, r.y + r.h - 5), Point(r.x + r.w - 5, r.y + r.h - 5) }) {
		VideoDriver->DrawRect(Region(p, Size(5, 5)), stud, true, BlitFlags::BLENDED);
	}
}

int CombatHud::StrokeTextWidth(const std::string& text, int height)
{
	float w = 0;
	for (char c : text) w += Advance(c);
	if (!text.empty() && text.back() != ' ') w -= GADV - GW;
	return int(w * height);
}

int CombatHud::DrawStrokeText(const std::string& text, const Point& topLeft, int height, const Color& color)
{
	float x = float(topLeft.x);
	const float h = float(height);
	const Color shadow(0, 0, 0, uint8_t(color.a * 0.7f));
	for (int pass = 0; pass < 2; ++pass) {
		float cx = x;
		const float off = pass == 0 ? std::max(1.0f, h / 14) : 0;
		for (char c : text) {
			for (const Seg& s : StrokeGlyph(c)) {
				Region r(int(cx + s.x0 * h + off), int(topLeft.y + s.y0 * h + off), std::max(1, int((s.x1 - s.x0) * h + 0.5f)), std::max(1, int((s.y1 - s.y0) * h + 0.5f)));
				VideoDriver->DrawRect(r, pass == 0 ? shadow : color, true, BlitFlags::BLENDED);
			}
			cx += Advance(c) * h;
		}
	}
	return StrokeTextWidth(text, height);
}

void CombatHud::DrawD20(const Point& center, float radius, float time, float settle, int face, const Color& tint, float alpha)
{
	const Mesh& mesh = D20();
	face = Clamp(face, 1, 20);
	const Face& shown = mesh.faces[mesh.faceOfNumber[face]];

	// a tumble on two axes; settling eases into the face's rest orientation
	Quat spin = AxisAngle({ 0.3f, 1.0f, 0.2f }, time * 9.0f) * AxisAngle({ 1.0f, 0.1f, 0.4f }, time * 5.3f);
	Quat q = Slerp(spin, shown.rest, Smooth(settle));

	auto project = [&](V3 p) {
		V3 r = Rotate(q, p);
		float persp = 1.0f + r.z * 0.12f;
		return std::make_pair(float(center.x) + r.x * radius * persp, float(center.y) - r.y * radius * persp);
	};

	std::vector<float> verts;
	std::vector<Color> colors;
	verts.reserve(20 * 6 + 600);
	colors.reserve(20 * 3 + 300);

	const V3 light = Normalize({ -0.45f, 0.6f, 0.75f });
	const V3 half = Normalize(light + V3 { 0, 0, 1 });
	const Color ink(48, 30, 18, 255);
	struct Visible {
		const Face* f;
		float facing;
		Color color;
	};
	std::vector<Visible> visible;
	for (const Face& f : mesh.faces) {
		V3 n = Rotate(q, f.normal);
		if (n.z <= 0.0f) continue;
		float diffuse = std::max(0.0f, Dot(n, light));
		float spec = std::pow(std::max(0.0f, Dot(n, half)), 24.0f) * 0.55f;
		float shade = 0.36f + 0.64f * diffuse;
		Color c(uint8_t(std::min(255.0f, tint.r * shade + 255 * spec)), uint8_t(std::min(255.0f, tint.g * shade + 255 * spec)),
			uint8_t(std::min(255.0f, tint.b * shade + 255 * spec)), uint8_t(255 * alpha));
		auto a = project(mesh.v[f.v[0]]);
		auto b = project(mesh.v[f.v[1]]);
		auto cc = project(mesh.v[f.v[2]]);
		PushTri(verts, colors, a.first, a.second, b.first, b.second, cc.first, cc.second, c);
		visible.push_back({ &f, n.z, c });
	}

	// the numbers, on the faces, turning with them
	for (const Visible& vis : visible) {
		if (vis.facing < 0.2f) continue;
		const Face& f = *vis.f;
		std::string number = std::to_string(f.number);
		const float gh = 0.38f;
		const float width = (number.size() * GADV - (GADV - GW)) * gh;
		Color digit = Mix(vis.color, Faded(ink, alpha), Smooth((vis.facing - 0.2f) / 0.45f));
		float gx = -width / 2;
		auto onFace = [&](float x, float y) { return project(f.center + f.right * x + f.up * y); };
		auto quad = [&](float x0, float y0, float x1, float y1) {
			// glyph y runs down, the face's up runs up
			auto p0 = onFace(x0, -y0);
			auto p1 = onFace(x1, -y0);
			auto p2 = onFace(x1, -y1);
			auto p3 = onFace(x0, -y1);
			PushTri(verts, colors, p0.first, p0.second, p1.first, p1.second, p2.first, p2.second, digit);
			PushTri(verts, colors, p0.first, p0.second, p2.first, p2.second, p3.first, p3.second, digit);
		};
		const float top = -gh / 2 + 0.02f;
		for (char c : number) {
			for (const Seg& s : StrokeGlyph(c)) {
				quad(gx + s.x0 * gh, top + s.y0 * gh, gx + s.x1 * gh, top + s.y1 * gh);
			}
			if (c == '6' || c == '9') {
				quad(gx, top + gh * 1.12f, gx + GW * gh, top + gh * 1.22f); // so 6 and 9 can be told apart
			}
			gx += GADV * gh;
		}
	}
	VideoDriver->DrawRawGeometry(verts, colors, BlitFlags::BLENDED);

	// edges
	const Color edge(40, 26, 14, uint8_t(170 * alpha));
	for (const Visible& vis : visible) {
		const Face& f = *vis.f;
		for (int i = 0; i < 3; ++i) {
			auto a = project(mesh.v[f.v[i]]);
			auto b = project(mesh.v[f.v[(i + 1) % 3]]);
			VideoDriver->DrawLine(Point(int(a.first), int(a.second)), Point(int(b.first), int(b.second)), edge, BlitFlags::BLENDED);
		}
	}
}

static void DrawGlow(const Point& center, float radius, const Color& color)
{
	std::vector<float> verts;
	std::vector<Color> colors;
	constexpr int SEGMENTS = 32;
	Color rim = color;
	rim.a = 0;
	for (int i = 0; i < SEGMENTS; ++i) {
		float a0 = float(i) / SEGMENTS * 6.2831853f;
		float a1 = float(i + 1) / SEGMENTS * 6.2831853f;
		verts.insert(verts.end(), { float(center.x), float(center.y), center.x + std::cos(a0) * radius, center.y + std::sin(a0) * radius,
					   center.x + std::cos(a1) * radius, center.y + std::sin(a1) * radius });
		colors.insert(colors.end(), { color, rim, rim });
	}
	VideoDriver->DrawRawGeometry(verts, colors, BlitFlags::BLENDED);
}

// ------------------------------------------------------------------------------------------
// the roll

float CombatHud::Scale() const
{
	int speed = std::max(10, int(core->GetDictionary().Get(StringView("Turn Based Combat Speed"), 100)));
	return 100.0f / float(speed);
}

tick_t CombatHud::LandStart() const
{
	return std::max(roll.resultAt, roll.start + tick_t(250 * Scale()));
}

tick_t CombatHud::Landed() const
{
	// a quick settle: the verdict has to show while the blow is still landing on screen
	return LandStart() + tick_t(120 * Scale());
}

static bool Special(int roll, bool critical)
{
	return roll == 1 || roll == 20 || critical;
}

tick_t CombatHud::VerdictAt() const
{
	// hit or miss reads out the moment the die lands, in step with the swing's hit frame
	return Landed();
}

void CombatHud::Reset()
{
	roll = Roll();
}

bool CombatHud::Holding() const
{
	if (!roll.active || !roll.hasResult) return false;
	tick_t now = GetMilliseconds();
	if (now > roll.resultAt + 5000) return false; // safety net
	return now < VerdictAt() + tick_t(200 * Scale());
}

void CombatHud::OnEvent(const CombatEvent& event, const String& attacker, const String& target)
{
	if (event.type == CombatEventType::CombatEnd) {
		// let the last roll finish showing
		return;
	}
	if (event.type == CombatEventType::SwingStart) {
		roll = Roll();
		roll.active = true;
		roll.attacker = attacker;
		roll.target = target;
		roll.start = GetMilliseconds();
		return;
	}
	if (event.type != CombatEventType::Swing) return;
	if (!roll.active || roll.hasResult) {
		// no wind-up seen (a reaction resolved at once ...): roll from here
		roll = Roll();
		roll.active = true;
		roll.attacker = attacker;
		roll.target = target;
		roll.start = GetMilliseconds();
	}
	roll.hasResult = true;
	roll.resultAt = GetMilliseconds();
	roll.roll = event.roll;
	roll.hit = event.hit;
	roll.critical = event.critical;
	roll.damage = event.value;
	roll.reaction = event.text == "reaction";
	// PerformAttack: roll + AC > THAC0 (2e) or roll + to-hit > defense; shown the friendly way
	// round, as roll + attack bonus against the total that hits
	if (Actor::IsReverseToHit()) {
		const int ac = event.bonus;
		const int thac0 = event.defense;
		roll.modifier = 20 - thac0;
		roll.needs = 21 - ac;
	} else {
		roll.modifier = event.bonus;
		roll.needs = event.defense + 1;
	}
}

void CombatHud::Draw(const Region& screen) const
{
	if (!roll.active || !core->GetDictionary().Get(StringView("Turn Based Dice Panel"), 1)) return;
	const tick_t now = GetMilliseconds();
	const float scale = Scale();

	float alpha = 1.0f;
	if (roll.hasResult) {
		const tick_t gone = VerdictAt() + tick_t(2200 * scale);
		if (now > gone + 400) return;
		if (now > gone) alpha = 1.0f - float(now - gone) / 400.0f;
	} else if (now > roll.start + 4000) {
		return; // never resolved
	}

	// wide enough for the die (radius 28) on the left and the sum beside it
	const Region panel(screen.x + 16, screen.y + screen.h * 28 / 100, 328, 142);
	DrawPanel(panel, alpha);

	Holder<Font> font = HudFont();
	const int line = font ? font->LineHeight : 14;
	if (font) {
		String header = roll.attacker + u"  attacks  " + roll.target;
		if (roll.reaction) header = u"Opportunity:  " + header;
		Font::PrintColors colors { Faded(Theme::textDim, alpha), ColorBlack };
		font->Print(Region(panel.x + 10, panel.y + 7, panel.w - 20, line + 2), header, IE_FONT_ALIGN_CENTER | IE_FONT_ALIGN_TOP | IE_FONT_SINGLE_LINE, colors);
	}

	const Point dieCenter(panel.x + 50, panel.y + 60);
	float radius = 28.0f;
	const bool landed = roll.hasResult && now >= Landed();
	const bool special = roll.hasResult && Special(roll.roll, roll.critical);
	const bool verdict = roll.hasResult && now >= VerdictAt();

	// spin time and how far it has settled
	float spinTime;
	float settle = 0;
	if (!roll.hasResult || now < LandStart()) {
		spinTime = float(now - roll.start) / 1000.0f;
	} else {
		const float land = float(Landed() - LandStart());
		const float u = std::min(1.0f, float(now - LandStart()) / std::max(1.0f, land));
		const float before = float(LandStart() - roll.start) / 1000.0f;
		spinTime = before + land / 1000.0f * (1 - (1 - u) * (1 - u)) / 2;
		settle = u;
	}
	if (landed) {
		// a little pop as it lands
		float t = std::min(1.0f, float(now - Landed()) / (160.0f * scale));
		radius *= 1.0f + 0.14f * std::sin(t * 3.14159f);
	} else {
		// bobbing as it spins
		radius *= 1.0f + 0.03f * std::sin(spinTime * 11.0f);
	}

	Color tint = kDieBone;
	if (special && verdict) {
		bool good = roll.hit;
		tint = good ? Color(255, 214, 110, 255) : Color(196, 86, 64, 255);
		const float pulse = 0.6f + 0.4f * std::sin(float(now - VerdictAt()) / 140.0f);
		Color glow = good ? Theme::crit : Theme::fumble;
		glow.a = uint8_t(150 * alpha * pulse);
		DrawGlow(dieCenter, radius * 1.75f, glow);
	}
	const int face = roll.hasResult ? Clamp(roll.roll, 1, 20) : 20;
	if (VideoDriver->CanDrawRawGeometry()) {
		DrawD20(dieCenter, radius, spinTime, settle, face, tint, alpha);
	} else if (landed) {
		std::string n = std::to_string(roll.roll);
		DrawStrokeText(n, Point(dieCenter.x - StrokeTextWidth(n, 42) / 2, dieCenter.y - 21), 42, Faded(Theme::text, alpha));
	}

	// the sum, a step at a time
	const int textH = 28;
	Point at(dieCenter.x + 42, dieCenter.y - textH / 2);
	const Color plain = Faded(Theme::text, alpha);
	const Color outcome = Faded(roll.hit ? Theme::hit : Theme::miss, alpha);
	String verdictText;
	Color verdictColor;
	if (special) {
		if (roll.hit) {
			verdictText = u"CRITICAL HIT!";
			verdictColor = Theme::crit;
		} else {
			verdictText = u"CRITICAL MISS!";
			verdictColor = Theme::fumble;
		}
		// natural 20 or 1: the modifiers don't matter, straight to the verdict
	} else if (landed) {
		const tick_t t0 = Landed();
		auto after = [&](int ms) { return now >= t0 + tick_t(ms * scale); };
		if (after(150)) {
			std::string mod = roll.modifier >= 0 ? "+ " + std::to_string(roll.modifier) : "- " + std::to_string(-roll.modifier);
			at.x += DrawStrokeText(mod, at, textH, plain) + 14;
		}
		if (after(280)) {
			at.x += DrawStrokeText("=", at, textH, plain) + 14;
		}
		if (after(400)) {
			const int total = roll.roll + roll.modifier;
			const int totalW = DrawStrokeText(std::to_string(total), at, textH, verdict ? outcome : plain);
			if (font) {
				// what it had to reach, small, beside the result
				Font::PrintColors dim { Faded(Theme::textDim, alpha * 0.85f), ColorBlack };
				font->Print(Region(at.x + totalW + 10, at.y + (textH - line) / 2, 90, line + 2), fmt::format(u"vs {}", roll.needs),
					    IE_FONT_ALIGN_LEFT | IE_FONT_ALIGN_TOP | IE_FONT_SINGLE_LINE, dim);
			}
		}
		verdictText = roll.hit ? u"HIT!" : u"MISS!";
		verdictColor = roll.hit ? Theme::hit : Theme::miss;
	}

	if (verdict && font) {
		// the verdict, popping in
		String text = verdictText;
		if (roll.hit && roll.damage > 0) text += fmt::format(u"   {} damage", roll.damage);
		const float t = std::min(1.0f, float(now - VerdictAt()) / (160.0f * scale));
		Font::PrintColors colors { Faded(verdictColor, alpha * t), ColorBlack };
		// bigger than the rest, drawn scaled
		const float zoom = VideoDriver->SupportsSceneTransform() ? 1.6f : 1.0f;
		const Size size = font->StringSize(text);
		const int y = panel.y + panel.h - int(line * zoom) - 10 - int((1 - t) * 6);
		const Point at(panel.x + panel.w / 2 - int(size.w * zoom / 2), y);
		if (zoom != 1.0f) VideoDriver->BeginScaledUI(zoom, at, panel);
		const Point origin = zoom != 1.0f ? Point() : at;
		font->Print(Region(origin, Size(size.w + 8, line + 4)), text, IE_FONT_ALIGN_LEFT | IE_FONT_ALIGN_TOP | IE_FONT_SINGLE_LINE, colors);
		if (zoom != 1.0f) VideoDriver->EndScaledUI();
	}
}

// ------------------------------------------------------------------------------------------
// combat floaters: stay a few seconds, white, slight random drift, stacked per creature

namespace {
struct CombatFloater {
	ieDword actor = 0;
	String text;
	tick_t start = 0;
	int stack = 0;
	float vx = 0;
	float vy = 0;
	Color color = ColorWhite;
};
std::vector<CombatFloater> floaters;
constexpr tick_t FLOATER_SHOWN = 4000;
constexpr tick_t FLOATER_FADE = 500;
constexpr int FLOATER_GAP = 4;
}

Color CombatHud::DamageColor(int type)
{
	if (!core->GetDictionary().Get(StringView("Elemental Damage Colors"), 1)) return ColorWhite;
	if (type & (DAMAGE_FIRE | DAMAGE_MAGICFIRE)) return Color(255, 138, 48, 255); // orange
	if (type & (DAMAGE_COLD | DAMAGE_MAGICCOLD)) return Color(122, 204, 255, 255); // ice blue
	if (type & DAMAGE_ELECTRICITY) return Color(250, 232, 88, 255); // yellow
	if (type & DAMAGE_ACID) return Color(176, 232, 64, 255); // lime
	if (type & DAMAGE_POISON) return Color(110, 196, 104, 255); // green
	if (type & DAMAGE_MAGIC) return Color(232, 128, 236, 255); // magenta
	return ColorWhite; // crushing, piercing, slashing, missile, stunning
}

void CombatHud::NotifySpellCast(ieDword actor, const ResRef& spell)
{
	if (spell.IsEmpty() || !core->GetDictionary().Get(StringView("Spell Cast Text"), 1)) return;
	const Spell* spl = gamedata->GetSpell(spell, true);
	if (!spl) return;
	// pst leaves the identified name as an empty string (strref 9999999): fall back
	String name = spl->SpellNameIdentified != ieStrRef::INVALID ? core->GetString(spl->SpellNameIdentified) : String();
	if (name.empty() && spl->SpellName != ieStrRef::INVALID) name = core->GetString(spl->SpellName);
	gamedata->FreeSpell(spl, spell, false);
	// a soft violet, apart from the white numbers and words of the fight
	if (!name.empty()) NotifyFloater(actor, std::move(name), Color(196, 170, 255, 255));
}

void CombatHud::NotifyFloater(ieDword actor, String text, const Color& color)
{
	if (text.empty() || !core->GetDictionary().Get(StringView("Turn Based Floating Text"), 1)) return;
	const tick_t now = GetMilliseconds();
	int stack = 0;
	for (const CombatFloater& f : floaters) {
		if (f.actor == actor) ++stack;
	}
	// a pixel or two over the whole life, in a random direction
	const float ang = float(RAND(0, 359)) * 3.14159265f / 180.0f;
	const float spd = float(RAND(6, 14)) / 10.0f;
	if (floaters.size() > 32) floaters.erase(floaters.begin());
	floaters.push_back({ actor, std::move(text), now, stack, std::cos(ang) * spd, std::sin(ang) * spd, color });
}

// Same lift as the original save die / "Save failed" label: 95 map-px above the
// feet for the die, and the text a bit below that so it sits on the crown.
static constexpr int DIE_LIFT = 95;
static constexpr int TEXT_LIFT = 80;

static Point Lifted(const Actor* actor, const Region& vp, int lift)
{
	return actor->Pos - Point(0, lift) - vp.origin;
}

static void WithDrawOffset(const Actor* actor, const std::function<void()>& draw)
{
	float ox = 0, oy = 0;
	const bool shifted = actor->DrawOffset(ox, oy);
	if (shifted) VideoDriver->SetObjectOffset(ox, oy);
	draw();
	if (shifted) VideoDriver->SetObjectOffset(0.0f, 0.0f);
}

// ------------------------------------------------------------------------------------------
// saving throws

namespace {
struct SaveRoll {
	ieDword actor = 0;
	int roll = 0;
	bool success = false;
	tick_t start = 0;
	bool sounded = false;
};
std::vector<SaveRoll> saves;
constexpr tick_t SAVE_SPIN = 220;
constexpr tick_t SAVE_SHOWN = 1100;
}

void CombatHud::NotifySave(ieDword actor, int roll, bool success)
{
	const tick_t now = GetMilliseconds();
	// every effect of a spell rolls the same save; show it once
	for (const SaveRoll& s : saves) {
		if (s.actor == actor && now - s.start < 500) return;
	}
	if (saves.size() > 16) saves.erase(saves.begin());
	saves.push_back({ actor, Clamp(roll, 1, 20), success, now, false });
	NotifyFloater(actor, success ? u"Saved" : u"Save failed");
}

void CombatHud::DrawWorldOverlays()
{
	if (floaters.empty() && saves.empty()) return;
	const GameControl* gc = core->GetGameControl();
	if (!gc) return;
	const Game* game = core->GetGame();
	const Map* area = game ? game->GetCurrentArea() : nullptr;
	if (!area) return;
	const Region vp = gc->Viewport();
	const tick_t now = GetMilliseconds();
	Holder<Font> font = HudFont();
	const int line = font ? font->LineHeight : 14;

	const bool dice = core->GetDictionary().Get(StringView("Turn Based Save Dice"), 1) != 0;
	for (auto it = saves.begin(); it != saves.end();) {
		SaveRoll& s = *it;
		const tick_t t = now - s.start;
		const Actor* actor = area->GetActorByGlobalID(s.actor);
		if (t > SAVE_SHOWN || !actor) {
			it = saves.erase(it);
			continue;
		}
		if (!dice) {
			++it;
			continue;
		}
		if (t >= SAVE_SPIN && !s.sounded) {
			s.sounded = true;
			core->GetAudioPlayback().Play(StringView(s.success ? "tbsaveok" : "tbsavefl"), AudioPreset::Spatial, SFXChannel::Actions, actor->Pos);
		}
		float alpha = t > SAVE_SHOWN - 300 ? float(SAVE_SHOWN - t) / 300.0f : 1.0f;
		const Point head = Lifted(actor, vp, DIE_LIFT);
		const bool landed = t >= SAVE_SPIN;
		const float settle = Clamp(float(t) / float(SAVE_SPIN), 0.0f, 1.0f);
		const Color outcome = s.success ? Theme::hit : Theme::miss;
		const float turn = landed ? Smooth(std::min(1.0f, float(t - SAVE_SPIN) / 200.0f)) : 0.0f;
		const Color tint = Mix(kDieBone, outcome, turn);
		float radius = 13.0f;
		if (landed) radius *= 1.0f + 0.2f * std::sin(std::min(1.0f, float(t - SAVE_SPIN) / 160.0f) * 3.14159f);
		if (VideoDriver->CanDrawRawGeometry()) {
			WithDrawOffset(actor, [&]() {
				DrawD20(head, radius, float(t) / 1000.0f * 2.0f, settle, s.roll, tint, alpha);
			});
		}
		++it;
	}

	if (!font) {
		floaters.clear();
		return;
	}
	for (auto it = floaters.begin(); it != floaters.end();) {
		CombatFloater& f = *it;
		const tick_t t = now - f.start;
		const Actor* actor = area->GetActorByGlobalID(f.actor);
		if (t > FLOATER_SHOWN || !actor) {
			it = floaters.erase(it);
			continue;
		}
		const float alpha = t > FLOATER_SHOWN - FLOATER_FADE ? float(FLOATER_SHOWN - t) / float(FLOATER_FADE) : 1.0f;
		const float sec = float(t) / 1000.0f;
		const Point head = Lifted(actor, vp, TEXT_LIFT);
		const Point at(head.x + int(f.vx * sec), head.y - f.stack * (line + FLOATER_GAP) + int(f.vy * sec));
		const Size size = font->StringSize(f.text);
		const int w = std::max(24, size.w + 8);
		const Font::PrintColors colors { Faded(f.color, alpha), Faded(ColorBlack, alpha) };
		WithDrawOffset(actor, [&]() {
			font->Print(Region(at.x - w / 2, at.y, w, line + 4), f.text,
				    IE_FONT_ALIGN_CENTER | IE_FONT_ALIGN_TOP | IE_FONT_SINGLE_LINE, colors);
		});
		++it;
	}
}

}
