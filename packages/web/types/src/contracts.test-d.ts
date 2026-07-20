import type { MonitoringProtocolCreate, MonitoringProtocolView } from "./geo";


type Equal<Left, Right> =
  (<Value>() => Value extends Left ? 1 : 2) extends
  (<Value>() => Value extends Right ? 1 : 2) ? true : false;
type Assert<Value extends true> = Value;

type CreateRequiresConcreteMinimum = Assert<Equal<
  MonitoringProtocolCreate["minimum_valid_repeats"],
  number
>>;

type LegacyViewAllowsNullMinimum = Assert<Equal<
  MonitoringProtocolView["minimum_valid_repeats"],
  number | null
>>;

export type MonitoringProtocolMinimumContract =
  | CreateRequiresConcreteMinimum
  | LegacyViewAllowsNullMinimum;
