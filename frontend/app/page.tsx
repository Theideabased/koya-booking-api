"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

type Slot = { id: string; provider: string; start: string; end: string; available: boolean };
type Booking = {
  id: string; slot_id: string; name: string; email: string;
  status: "confirmed" | "cancelled"; created_at: string;
};

function message(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/${path}`, { ...init, cache: "no-store" });
  const data = await response.json();
  if (!response.ok) {
    const detail = data?.error;
    if (response.status === 429) throw new Error("Too many requests. Please wait a minute and try again.");
    if (response.status === 409 && path === "bookings") throw new Error("This appointment has just been taken. Choose another time.");
    throw new Error(typeof detail === "string" ? detail : "We couldn't complete that request. Please try again.");
  }
  return data as T;
}

function formatDate(value: string, options: Intl.DateTimeFormatOptions) {
  return new Intl.DateTimeFormat("en-NG", { timeZone: "Africa/Lagos", ...options }).format(new Date(value));
}

export default function Home() {
  const [slots, setSlots] = useState<Slot[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [selected, setSelected] = useState<Slot | null>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [booking, setBooking] = useState<Booking | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");
  const [retryKey, setRetryKey] = useState("");
  const [searchEmail, setSearchEmail] = useState("");
  const [myBookings, setMyBookings] = useState<Booking[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [searched, setSearched] = useState(false);

  async function loadSlots() {
    setLoading(true);
    setLoadError("");
    try {
      const data = await api<{ slots: Slot[] }>("slots");
      setSlots(data.slots);
    } catch (error) {
      setLoadError(message(error));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadSlots(); }, []);

  const days = useMemo(() => {
    const groups = new Map<string, Slot[]>();
    for (const slot of slots.filter((item) => item.available)) {
      const date = formatDate(slot.start, { weekday: "long", month: "long", day: "numeric" });
      groups.set(date, [...(groups.get(date) || []), slot]);
    }
    return [...groups.entries()];
  }, [slots]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || submitting) return;
    setSubmitting(true);
    setFormError("");
    const key = retryKey || crypto.randomUUID();
    setRetryKey(key);
    try {
      const result = await api<Booking>("bookings", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": key },
        body: JSON.stringify({
          slot_id: selected.id,
          name: name.trim(),
          email: email.trim(),
        }),
      });
      setBooking(result);
      setRetryKey("");
      void loadSlots();
    } catch (error) {
      setFormError(message(error));
      if (message(error).includes("just been taken")) setRetryKey("");
    } finally {
      setSubmitting(false);
    }
  }

  async function findBookings(cursor?: string) {
    setSearching(true);
    setSearchError("");
    try {
      const params = new URLSearchParams({ email: searchEmail.trim(), limit: "5" });
      if (cursor) params.set("cursor", cursor);
      const data = await api<{ bookings: Booking[]; next_cursor: string | null }>(`bookings?${params}`);
      setMyBookings(cursor ? [...myBookings, ...data.bookings] : data.bookings);
      setNextCursor(data.next_cursor);
      setSearched(true);
    } catch (error) {
      setSearchError(message(error));
    } finally {
      setSearching(false);
    }
  }

  async function cancel(id: string) {
    setSearchError("");
    try {
      const result = await api<Booking>(`bookings/${id}`, { method: "DELETE" });
      setMyBookings((items) => items.map((item) => item.id === id ? result : item));
      if (booking?.id === id) setBooking(result);
      void loadSlots();
    } catch (error) {
      setSearchError(message(error));
    }
  }

  return <main className="page-shell">
    <header className="site-header">
      <a className="brand" href="/" aria-label="Koya Clinic home"><span className="brand-mark">K</span><span>Koya <strong>Clinic</strong></span></a>
      <span className="header-note">Appointment booking</span>
    </header>

    <section className="hero">
      <p className="eyebrow">YOUR CARE, ON YOUR TIME</p>
      <h1>Make space for <em>better health.</em></h1>
      <p className="hero-copy">Choose a time that works for you. Your appointment is confirmed as soon as you book.</p>
      <div className="hero-meta"><span className="meta-dot" /> Available appointments shown in Lagos time (WAT)</div>
    </section>

    <div className="content-grid">
      <section className="panel slot-panel" aria-labelledby="slots-title">
        <div className="section-heading"><div><p className="section-step">01 / CHOOSE A TIME</p><h2 id="slots-title">Available appointments</h2></div><button className="text-button" type="button" onClick={() => void loadSlots()} disabled={loading}>Refresh</button></div>
        {loading && <div aria-label="Loading appointments" className="skeleton-list"><div /><div /><div /></div>}
        {!loading && loadError && <div className="feedback error" role="alert"><strong>Couldn’t load appointments</strong><p>{loadError}</p><button type="button" onClick={() => void loadSlots()}>Try again</button></div>}
        {!loading && !loadError && days.length === 0 && <div className="feedback"><strong>No appointments available right now</strong><p>Please check back soon for new times.</p><button type="button" onClick={() => void loadSlots()}>Check again</button></div>}
        {!loading && !loadError && days.map(([day, times]) => <div className="day-group" key={day}><h3>{day}</h3><div className="time-grid">{times.map((slot) => <button key={slot.id} type="button" className={`time-slot ${selected?.id === slot.id ? "selected" : ""}`} aria-pressed={selected?.id === slot.id} onClick={() => { setSelected(slot); setBooking(null); setFormError(""); setRetryKey(""); }}><span>{formatDate(slot.start, { hour: "numeric", minute: "2-digit" })}</span><span className="slot-arrow" aria-hidden="true">↗</span></button>)}</div></div>)}
      </section>

      <section className="panel form-panel" aria-labelledby="details-title">
        {booking ? <div className="confirmation" role="status"><div className="success-icon" aria-hidden="true">✓</div><p className="section-step">APPOINTMENT {booking.status.toUpperCase()}</p><h2>{booking.status === "confirmed" ? "You’re all set." : "Appointment cancelled."}</h2><p>{booking.status === "confirmed" ? "Your appointment has been reserved. Save your confirmation number for reference." : "This time is available again."}</p><div className="confirmation-card"><span>Confirmation number</span><strong>{booking.id}</strong><span>Patient</span><strong>{booking.name}</strong><span>Time</span><strong>{formatDate(slots.find((slot) => slot.id === booking.slot_id)?.start || selected?.start || booking.created_at, { weekday: "long", month: "long", day: "numeric", hour: "numeric", minute: "2-digit" })} WAT</strong></div><button className="primary-button" type="button" onClick={() => { setBooking(null); setSelected(null); setName(""); setEmail(""); }}>Book another appointment</button></div>
          : <><div className="section-heading"><div><p className="section-step">02 / YOUR DETAILS</p><h2 id="details-title">Confirm your visit</h2></div></div><p className="form-intro">{selected ? <>Selected: <strong>{formatDate(selected.start, { weekday: "long", month: "long", day: "numeric", hour: "numeric", minute: "2-digit" })} WAT · {selected.provider}</strong></> : "Select an appointment time to continue."}</p><form onSubmit={(event) => void submit(event)} aria-busy={submitting}><label htmlFor="patient-name">Full name</label><input id="patient-name" value={name} onChange={(event) => { setName(event.target.value); setRetryKey(""); }} autoComplete="name" maxLength={120} required placeholder="Your full name" /><label htmlFor="patient-email">Email address</label><input id="patient-email" type="email" value={email} onChange={(event) => { setEmail(event.target.value); setRetryKey(""); }} autoComplete="email" required placeholder="you@example.com" />{formError && <p className="form-error" role="alert">{formError}</p>}<button className="primary-button" type="submit" disabled={!selected || submitting}>{submitting ? "Confirming…" : "Confirm appointment"}<span aria-hidden="true">→</span></button></form><p className="privacy-note">Your details are used only for this booking.</p></>}
      </section>
    </div>

    <section className="panel bookings-panel" aria-labelledby="manage-title"><div className="section-heading"><div><p className="section-step">YOUR APPOINTMENTS</p><h2 id="manage-title">Find a booking</h2></div></div><p className="manage-intro">Enter the email you used to book to see your appointments.</p><form className="search-form" onSubmit={(event) => { event.preventDefault(); void findBookings(); }}><label htmlFor="search-email">Email address</label><div><input id="search-email" type="email" value={searchEmail} onChange={(event) => { setSearchEmail(event.target.value); setSearched(false); setMyBookings([]); setNextCursor(null); }} autoComplete="email" placeholder="you@example.com" required /><button className="secondary-button" type="submit" disabled={searching}>{searching ? "Searching…" : "Find bookings"}</button></div></form>{searchError && <p className="form-error" role="alert">{searchError}</p>}{searched && !searching && myBookings.length === 0 && <p className="empty-bookings">No bookings found for this email.</p>}{myBookings.length > 0 && <div className="booking-list">{myBookings.map((item) => <div className="booking-row" key={item.id}><div><strong>{item.name}</strong><p>#{item.id.slice(0, 8)} · {item.status}</p></div><button type="button" className="text-button" onClick={() => void cancel(item.id)} disabled={item.status === "cancelled"}>{item.status === "confirmed" ? "Cancel booking" : "Cancelled"}</button></div>)}{nextCursor && <button className="text-button load-more" type="button" disabled={searching} onClick={() => void findBookings(nextCursor)}>{searching ? "Loading…" : "Load more"}</button>}</div>}</section>
    <footer>KOYA CLINIC <span>Care starts here.</span></footer>
  </main>;
}
