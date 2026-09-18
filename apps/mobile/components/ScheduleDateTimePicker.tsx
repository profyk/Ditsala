import { useMemo, useState } from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";

interface ScheduleDateTimePickerProps {
  value: Date | null;
  onChange: (date: Date) => void;
  testID?: string;
}

const WEEKDAY_LABELS = ["S", "M", "T", "W", "T", "F", "S"];
const MONTH_LABELS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];
// 15-minute increments across a full day — a plain scrollable list of
// slots rather than a native wheel picker, so this needs no additional
// native dependency (see docs/SECURITY_GAPS.md's note on why a real
// `@react-native-community/datetimepicker` wasn't added this pass).
const TIME_SLOTS: { hour: number; minute: number }[] = Array.from({ length: 24 * 4 }, (_, i) => ({
  hour: Math.floor(i / 4),
  minute: (i % 4) * 15,
}));

function startOfDay(date: Date): Date {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return d;
}

function formatTimeSlot(hour: number, minute: number): string {
  const period = hour < 12 ? "AM" : "PM";
  const displayHour = hour % 12 === 0 ? 12 : hour % 12;
  return `${displayHour}:${minute.toString().padStart(2, "0")} ${period}`;
}

function formatSelected(date: Date): string {
  return date.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * A dependency-free popup calendar + time-of-day picker for scheduling a
 * meeting (docs/DITSALA_MEET_SPEC.md §9 Phase 4). Built from plain RN
 * primitives instead of a native date-picker module — this dev
 * environment's resources made adding a new native dependency risky to
 * install and, either way, unverifiable beyond type-checking (no
 * simulator/device here — same boundary as every other mobile phase).
 */
export function ScheduleDateTimePicker({ value, onChange, testID }: ScheduleDateTimePickerProps) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<"date" | "time">("date");
  const [visibleMonth, setVisibleMonth] = useState(() => startOfDay(value ?? new Date()));
  const [pendingDate, setPendingDate] = useState<Date | null>(value);

  const today = useMemo(() => startOfDay(new Date()), []);

  const daysGrid = useMemo(() => {
    const year = visibleMonth.getFullYear();
    const month = visibleMonth.getMonth();
    const firstOfMonth = new Date(year, month, 1);
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const leadingBlanks = firstOfMonth.getDay();
    const cells: (Date | null)[] = Array.from({ length: leadingBlanks }, () => null);
    for (let day = 1; day <= daysInMonth; day++) {
      cells.push(new Date(year, month, day));
    }
    return cells;
  }, [visibleMonth]);

  function openPicker() {
    setPendingDate(value);
    setVisibleMonth(startOfDay(value ?? new Date()));
    setStep("date");
    setOpen(true);
  }

  function selectDay(day: Date) {
    const combined = new Date(day);
    if (pendingDate) {
      combined.setHours(pendingDate.getHours(), pendingDate.getMinutes());
    }
    setPendingDate(combined);
    setStep("time");
  }

  function selectTime(hour: number, minute: number) {
    const base = pendingDate ?? today;
    const combined = new Date(base);
    combined.setHours(hour, minute, 0, 0);
    setPendingDate(combined);
    onChange(combined);
    setOpen(false);
  }

  return (
    <>
      <Pressable
        testID={testID}
        onPress={openPicker}
        className="mb-5 rounded-xl border border-border bg-surface px-4 py-3"
      >
        <Text className="mb-1 text-sm font-medium text-text-secondary">Date & time</Text>
        <Text className="text-base text-text-primary">
          {value ? formatSelected(value) : "Choose when to meet"}
        </Text>
      </Pressable>

      <Modal visible={open} animationType="slide" transparent onRequestClose={() => setOpen(false)}>
        <View className="flex-1 justify-end bg-black/60">
          <View className="max-h-[80%] rounded-t-2xl bg-surface p-5">
            {step === "date" ? (
              <>
                <View className="mb-4 flex-row items-center justify-between">
                  <Pressable
                    testID="calendar-prev-month"
                    onPress={() =>
                      setVisibleMonth(
                        new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() - 1, 1)
                      )
                    }
                    className="px-3 py-2"
                  >
                    <Text className="text-lg text-accent">‹</Text>
                  </Pressable>
                  <Text className="text-base font-semibold text-text-primary">
                    {MONTH_LABELS[visibleMonth.getMonth()]} {visibleMonth.getFullYear()}
                  </Text>
                  <Pressable
                    testID="calendar-next-month"
                    onPress={() =>
                      setVisibleMonth(
                        new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() + 1, 1)
                      )
                    }
                    className="px-3 py-2"
                  >
                    <Text className="text-lg text-accent">›</Text>
                  </Pressable>
                </View>
                <View className="mb-2 flex-row">
                  {WEEKDAY_LABELS.map((label, i) => (
                    <View key={i} className="flex-1 items-center">
                      <Text className="text-xs font-medium text-text-tertiary">{label}</Text>
                    </View>
                  ))}
                </View>
                <View className="flex-row flex-wrap">
                  {daysGrid.map((day, i) => {
                    const disabled = day !== null && day < today;
                    const isSelected =
                      day !== null &&
                      pendingDate !== null &&
                      startOfDay(day).getTime() === startOfDay(pendingDate).getTime();
                    return (
                      <View key={i} style={{ width: `${100 / 7}%` }} className="items-center py-1">
                        {day ? (
                          <Pressable
                            disabled={disabled}
                            onPress={() => selectDay(day)}
                            className={[
                              "h-9 w-9 items-center justify-center rounded-full",
                              isSelected ? "bg-accent" : "",
                            ].join(" ")}
                          >
                            <Text
                              className={
                                isSelected
                                  ? "font-semibold text-white"
                                  : disabled
                                    ? "text-text-tertiary"
                                    : "text-text-primary"
                              }
                            >
                              {day.getDate()}
                            </Text>
                          </Pressable>
                        ) : null}
                      </View>
                    );
                  })}
                </View>
              </>
            ) : (
              <>
                <View className="mb-4 flex-row items-center justify-between">
                  <Pressable testID="calendar-back-to-date" onPress={() => setStep("date")}>
                    <Text className="text-base text-accent">‹ Back</Text>
                  </Pressable>
                  <Text className="text-base font-semibold text-text-primary">
                    {pendingDate ? formatSelected(pendingDate).split(",")[0] : ""}
                  </Text>
                  <View className="w-12" />
                </View>
                <ScrollView className="max-h-96">
                  {TIME_SLOTS.map(({ hour, minute }) => (
                    <Pressable
                      key={`${hour}:${minute}`}
                      testID={`time-slot-${hour}-${minute}`}
                      onPress={() => selectTime(hour, minute)}
                      className="border-b border-border py-3 active:bg-surface-raised"
                    >
                      <Text className="text-base text-text-primary">
                        {formatTimeSlot(hour, minute)}
                      </Text>
                    </Pressable>
                  ))}
                </ScrollView>
              </>
            )}
            <Pressable
              testID="calendar-cancel"
              onPress={() => setOpen(false)}
              className="mt-4 items-center py-3"
            >
              <Text className="text-sm text-text-tertiary">Cancel</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </>
  );
}
